package main

import (
	"strconv"
	"encoding/binary"
	"encoding/json"
	"fmt"
	"math"
	"os"
	"runtime"
	"sync"
)

type VB struct {
	Off, Size, Count, Stride int
	Meshopt, Zstd            bool
	Fields                   map[string][2]int
}
type IB struct {
	Off, Size, Count, Isize int
	Meshopt, Seq            bool
}
type Draw struct {
	Vbs                []int
	Ib, Base, Start, N int
	Prim               string
	Lm, Cast           bool
	Mat                string
	Inst               [][]float64
}
type Mesh struct {
	Model string
	Vbs   []VB
	Ibs   []IB
	Draws []Draw
}
type Manifest struct {
	Map        string
	LmUvScale  []float64 `json:"lm_uv_scale"`
	Meshes     []Mesh
}

// LmTri: a lightmapped triangle (world space) with lightmap uv and vertex normals
type LmTri struct {
	P  [3][3]float32
	N  [3][3]float32
	UV [3][2]float32
	Lab int32 // index into Scene.LmLabels
}

type Scene struct {
	Cast  [][9]float32 // caster triangles
	CastMat []int32
	Mats []string
	LmTri []LmTri
	LmLabels []string
}

func f32(b []byte) float32 { return math.Float32frombits(binary.LittleEndian.Uint32(b)) }

func decodeNormal(p uint32) [3]float32 {
	x := float32((p>>12)&0x3ff)/1023*2 - 1
	y := float32((p>>22)&0x3ff)/1023*2 - 1
	z := 1 - abs32(x) - abs32(y)
	nz := clamp32(-z, 0, 1)
	if x >= 0 {
		x -= nz
	} else {
		x += nz
	}
	if y >= 0 {
		y -= nz
	} else {
		y += nz
	}
	l := float32(math.Sqrt(float64(x*x + y*y + z*z)))
	if l == 0 {
		return [3]float32{0, 0, 1}
	}
	return [3]float32{x / l, y / l, z / l}
}

func abs32(v float32) float32 {
	if v < 0 {
		return -v
	}
	return v
}
func clamp32(v, a, b float32) float32 {
	if v < a {
		return a
	}
	if v > b {
		return b
	}
	return v
}

func xform(t []float64, p [3]float32) [3]float32 {
	x, y, z := float64(p[0]), float64(p[1]), float64(p[2])
	return [3]float32{
		float32(t[0]*x + t[1]*y + t[2]*z + t[3]),
		float32(t[4]*x + t[5]*y + t[6]*z + t[7]),
		float32(t[8]*x + t[9]*y + t[10]*z + t[11]),
	}
}
func xformDir(t []float64, p [3]float32) [3]float32 {
	x, y, z := float64(p[0]), float64(p[1]), float64(p[2])
	v := [3]float32{
		float32(t[0]*x + t[1]*y + t[2]*z),
		float32(t[4]*x + t[5]*y + t[6]*z),
		float32(t[8]*x + t[9]*y + t[10]*z),
	}
	return norm(v)
}

type decoded struct {
	data   []byte
	stride int
	count  int
	fields map[string][2]int
}

func loadScene(dir string, castOverride func(string) bool) (*Manifest, *Scene, error) {
	mf := &Manifest{}
	jb, err := os.ReadFile(dir + "/geom.json")
	if err != nil {
		return nil, nil, err
	}
	if err := json.Unmarshal(jb, mf); err != nil {
		return nil, nil, err
	}
	blob, err := os.ReadFile(dir + "/geom.bin")
	if err != nil {
		return nil, nil, err
	}
	sc := &Scene{}
	matIdx := map[string]int32{}
	lmIdx := map[string]int32{}
	var mu sync.Mutex
	var wg sync.WaitGroup
	jobs := make(chan int)
	errs := 0
	nrm := [2]int{}
	for w := 0; w < runtime.NumCPU(); w++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			for mi := range jobs {
				m := &mf.Meshes[mi]
				vbs := make([]decoded, len(m.Vbs))
				ok := true
				for i, vb := range m.Vbs {
					src := blob[vb.Off : vb.Off+vb.Size]
					d := make([]byte, vb.Count*vb.Stride)
					if vb.Meshopt {
						if err := decodeVertexBuffer(d, vb.Count, vb.Stride, src); err != nil {
							fmt.Println("vb", m.Model, err)
							ok = false
						}
					} else {
						copy(d, src)
					}
					vbs[i] = decoded{d, vb.Stride, vb.Count, vb.Fields}
				}
				ibs := make([][]uint32, len(m.Ibs))
				for i, ib := range m.Ibs {
					src := blob[ib.Off : ib.Off+ib.Size]
					if ib.Meshopt {
						idx, err := decodeIndexBuffer(ib.Count, src)
						if err != nil {
							fmt.Println("ib", m.Model, err)
							ok = false
						}
						ibs[i] = idx
					} else {
						ibs[i] = rawIndices(src, ib.Count, ib.Isize)
					}
				}
				if !ok {
					mu.Lock()
					errs++
					mu.Unlock()
					continue
				}
				var cast [][9]float32
				var castMat []string
				var lm []LmTri
				var lmLab []string
				nOK, nBad := 0, 0
				for di, dr := range m.Draws {
					if dr.Prim != "RENDER_PRIM_TRIANGLES" {
						continue
					}
					// find attribute sources
					var pv, uvv, nv *decoded
					var po, uvo, no, uvf, pf int
					for _, vi := range dr.Vbs {
						v := &vbs[vi]
						if f, ok := v.fields["POSITION0"]; ok && pv == nil {
							pv, po, pf = v, f[1], f[0]
						}
						if f, ok := v.fields["TEXCOORD3"]; ok {
							uvv, uvo, uvf = v, f[1], f[0]
						}
						if f, ok := v.fields["NORMAL0"]; ok && f[0] == 42 {
							nv, no = v, f[1]
						}
					}
					if pv == nil || pf != 6 {
						continue
					}
					idx := ibs[dr.Ib][dr.Start : dr.Start+dr.N]
					pos := func(i uint32) [3]float32 {
						o := int(i)*pv.stride + po
						return [3]float32{f32(pv.data[o:]), f32(pv.data[o+4:]), f32(pv.data[o+8:])}
					}
					doCast := dr.Cast
					if castOverride != nil {
						doCast = castOverride(dr.Mat)
					}
					for _, t := range dr.Inst {
						for k := 0; k+2 < len(idx); k += 3 {
							i0, i1, i2 := idx[k]+uint32(dr.Base), idx[k+1]+uint32(dr.Base), idx[k+2]+uint32(dr.Base)
							if int(i0) >= pv.count || int(i1) >= pv.count || int(i2) >= pv.count {
								continue
							}
							a, b, c := xform(t, pos(i0)), xform(t, pos(i1)), xform(t, pos(i2))
							if doCast {
								cast = append(cast, [9]float32{a[0], a[1], a[2], b[0], b[1], b[2], c[0], c[1], c[2]})
								castMat = append(castMat, m.Model+drawTag(di)+" | "+dr.Mat)
							}
							if dr.Lm && uvv != nil && uvf == 35 && len(dr.Inst) == 1 {
								lt := LmTri{P: [3][3]float32{a, b, c}}
								fn := norm(cross(sub(b, a), sub(c, a)))
								for j, ii := range [3]uint32{i0, i1, i2} {
									o := int(ii)*uvv.stride + uvo
									lt.UV[j] = [2]float32{float32(binary.LittleEndian.Uint16(uvv.data[o:])) / 65535, float32(binary.LittleEndian.Uint16(uvv.data[o+2:])) / 65535}
									if nv != nil {
										n := decodeNormal(binary.LittleEndian.Uint32(nv.data[int(ii)*nv.stride+no:]))
										lt.N[j] = xformDir(t, n)
									} else {
										lt.N[j] = fn
									}
									if dot(lt.N[j], fn) > 0.3 {
										nOK++
									} else {
										nBad++
									}
								}
								lm = append(lm, lt)
								lmLab = append(lmLab, m.Model+" #"+strconv.Itoa(di)+" | "+dr.Mat)
							}
						}
					}
				}
				mu.Lock()
				sc.Cast = append(sc.Cast, cast...)
				for _, s := range castMat {
					id, ok := matIdx[s]
					if !ok {
						id = int32(len(sc.Mats))
						matIdx[s] = id
						sc.Mats = append(sc.Mats, s)
					}
					sc.CastMat = append(sc.CastMat, id)
				}
				for k := range lm {
					id, ok := lmIdx[lmLab[k]]
					if !ok {
						id = int32(len(sc.LmLabels))
						lmIdx[lmLab[k]] = id
						sc.LmLabels = append(sc.LmLabels, lmLab[k])
					}
					lm[k].Lab = id
				}
				sc.LmTri = append(sc.LmTri, lm...)
				nrm[0] += nOK
				nrm[1] += nBad
				mu.Unlock()
			}
		}()
	}
	for i := range mf.Meshes {
		jobs <- i
	}
	close(jobs)
	wg.Wait()
	fmt.Printf("meshes %d (decode errors %d) casters %d lightmapped tris %d normals ok/bad %d/%d\n", len(mf.Meshes), errs, len(sc.Cast), len(sc.LmTri), nrm[0], nrm[1])
	return mf, sc, nil
}

func sub(a, b [3]float32) [3]float32 { return [3]float32{a[0] - b[0], a[1] - b[1], a[2] - b[2]} }
func add(a, b [3]float32) [3]float32 { return [3]float32{a[0] + b[0], a[1] + b[1], a[2] + b[2]} }
func scale(a [3]float32, s float32) [3]float32 {
	return [3]float32{a[0] * s, a[1] * s, a[2] * s}
}
func dot(a, b [3]float32) float32 { return a[0]*b[0] + a[1]*b[1] + a[2]*b[2] }
func cross(a, b [3]float32) [3]float32 {
	return [3]float32{a[1]*b[2] - a[2]*b[1], a[2]*b[0] - a[0]*b[2], a[0]*b[1] - a[1]*b[0]}
}
func norm(a [3]float32) [3]float32 {
	l := float32(math.Sqrt(float64(dot(a, a))))
	if l == 0 {
		return a
	}
	return scale(a, 1/l)
}
