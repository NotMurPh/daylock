package main

// sunbake: bake sun visibility for Deadlock lightmaps / probe points.
//   sunbake lightmap -geom DIR -out DIR [-size 8192] [-az 135 -el 50] [-samples 8] [-cone 1.0]
//   sunbake points   -geom DIR -in pts.f32 -out vis.bin [-az -el -samples -cone -sky 64]
// outputs (lightmap): vis.u8 (sun visibility 0..255), ndl.u8 (N.L 0..255), cov.u8 (1 = covered), nrm.u8 (xyz*127+128)

import (
	"encoding/binary"
	"flag"
	"fmt"
	"math"
	"os"
	"runtime"
	"sync"
	"sync/atomic"
	"time"
)

var rayZ float64
var skyRays int

type rng uint64

func (r *rng) f() float32 {
	x := uint64(*r)
	x ^= x << 13
	x ^= x >> 7
	x ^= x << 17
	*r = rng(x)
	return float32(x>>40) / float32(1<<24)
}

func basis(n [3]float32) ([3]float32, [3]float32) {
	var a [3]float32
	if abs32(n[0]) > 0.9 {
		a = [3]float32{0, 1, 0}
	} else {
		a = [3]float32{1, 0, 0}
	}
	u := norm(cross(n, a))
	v := cross(n, u)
	return u, v
}

func sunDir(az, el float64) [3]float32 {
	a, e := az*math.Pi/180, el*math.Pi/180
	return [3]float32{float32(math.Cos(e) * math.Cos(a)), float32(math.Cos(e) * math.Sin(a)), float32(math.Sin(e))}
}

func coneSample(L, u, v [3]float32, cone float32, r *rng) [3]float32 {
	rr := cone * float32(math.Sqrt(float64(r.f())))
	ph := 2 * math.Pi * float64(r.f())
	s := float32(math.Sin(float64(rr)))
	c := float32(math.Cos(float64(rr)))
	cp, sp := float32(math.Cos(ph)), float32(math.Sin(ph))
	return norm(add(scale(L, c), add(scale(u, s*cp), scale(v, s*sp))))
}

func main() {
	if len(os.Args) < 2 {
		fmt.Println("usage: sunbake lightmap|points ...")
		os.Exit(2)
	}
	mode := os.Args[1]
	fs := flag.NewFlagSet(mode, flag.ExitOnError)
	geom := fs.String("geom", "", "geometry dir (extract_geom.py output)")
	out := fs.String("out", "", "output dir / file")
	in := fs.String("in", "", "points file (float32 xyz)")
	size := fs.Int("size", 8192, "lightmap size")
	az := fs.Float64("az", 135, "sun azimuth (deg, from +x toward +y)")
	el := fs.Float64("el", 50, "sun elevation (deg)")
	samples := fs.Int("samples", 8, "rays per texel")
	cone := fs.Float64("cone", 1.0, "sun cone half-angle (deg)")
	sky := fs.Int("sky", 0, "points: sky visibility rays")
	fs.Float64Var(&rayZ, "z", 600, "ray debug height")
	fs.IntVar(&skyRays, "skyvis", 0, "lightmap: sky visibility rays per texel")
	pick := fs.String("pick", "", "pick: camera x,y,z,yaw0,yaw1,pitch0,pitch1 (deg)")
	fs.Parse(os.Args[2:])
	t0 := time.Now()
	var override func(string) bool
	if os.Getenv("SUNBAKE_ALLCAST") == "1" {
		override = func(string) bool { return true }
	}
	_, sc, err := loadScene(*geom, override)
	if err != nil {
		fmt.Println(err)
		os.Exit(1)
	}
	fmt.Printf("[%.1fs] loaded\n", time.Since(t0).Seconds())
	if mode == "lmbox" {
		lmBox(sc, *pick, *out, *size)
		return
	}
	if mode == "lmmask" {
		lmMask(sc, *pick, *out, *size)
		return
	}
	if mode == "samples" {
		samplesMode(sc, *pick)
		return
	}
	if mode == "bounds" {
		boundsMode(sc, *pick)
		return
	}
	bvh := buildBVH(sc.Cast)
	sc.Cast = nil
	runtime.GC()
	fmt.Printf("[%.1fs] bvh nodes %d\n", time.Since(t0).Seconds(), len(bvh.Nodes))
	L := sunDir(*az, *el)
	coneR := float32(*cone * math.Pi / 180)
	lu, lv := basis(L)
	if mode == "sunscan" {
		sunScan(bvh, sc, *pick)
		return
	}
	switch mode {
	case "lightmap":
		bakeLightmap(bvh, sc, *out, *size, L, lu, lv, coneR, *samples, t0)
	case "at":
		for _, p := range [][3]float32{{8300, -400, 450}, {-8300, 400, 460}, {0, -1500, 300}, {1280, 6900, 900}} {
			for _, d := range [][3]float32{L, {0, 0, 1}, norm([3]float32{0.3, 0.2, 1})} {
				id, t := bvh.Closest(p, d, 80000)
				name := "-"
				if id >= 0 {
					name = sc.Mats[sc.CastMat[id]]
				}
				fmt.Printf("%v dir %v -> %.0f %s\n", p, d, t, name)
			}
		}
	case "short":
		// sample lightmapped upward triangles, cast toward sun, report short blockers
		cnt := map[int32]int{}
		var hist [6]int
		for i := 0; i < len(sc.LmTri); i += 37 {
			t := &sc.LmTri[i]
			ng := norm(cross(sub(t.P[1], t.P[0]), sub(t.P[2], t.P[0])))
			if dot(ng, add(t.N[0], add(t.N[1], t.N[2]))) < 0 {
				ng = scale(ng, -1)
			}
			if ng[2] < 0.9 {
				continue
			}
			p := scale(add(t.P[0], add(t.P[1], t.P[2])), 1.0/3)
			id, d := bvh.Closest(add(p, add(ng, scale(L, 0.5))), L, 80000)
			switch {
			case id < 0:
				hist[0]++
			case d < 5:
				hist[1]++
			case d < 30:
				hist[2]++
			case d < 200:
				hist[3]++
			default:
				hist[4]++
			}
			if id >= 0 && d < 30 {
				cnt[sc.CastMat[id]]++
			}
		}
		fmt.Println("free, <5, <30, <200, far:", hist)
		for id, c := range cnt {
			if c >= 20 {
				fmt.Printf("%6d %s\n", c, sc.Mats[id])
			}
		}
	case "lmat":
		lmAt(bvh, sc, [3]float32{8300, -400, 400}, 250)
	case "topdown":
		topdown(bvh, L, "topdown.pgm")
	case "ray":
		// debug: from a grid of points high above streets, cast toward the sun and report what blocks
		cnt := map[int32]int{}
		dist := map[int32]float32{}
		total, blocked := 0, 0
		for x := -9000; x <= 9000; x += 500 {
			for y := -9000; y <= 6000; y += 500 {
				o := [3]float32{float32(x), float32(y), float32(rayZ)}
				total++
				id, t := bvh.Closest(o, L, 80000)
				if id >= 0 {
					blocked++
					cnt[sc.CastMat[id]]++
					dist[sc.CastMat[id]] = t
				}
			}
		}
		fmt.Println("total", total, "blocked", blocked)
		for id, c := range cnt {
			if c >= 3 {
				fmt.Printf("%5d  %8.0f  %s\n", c, dist[id], sc.Mats[id])
			}
		}
	case "pick":
		pickMode(bvh, sc, *pick)
	case "los":
		losMode(bvh, *in, *out)
	case "points":
		bakePoints(bvh, *in, *out, L, lu, lv, coneR, *samples, *sky, t0)
	}
}

func bakeLightmap(bvh *BVH, sc *Scene, out string, W int, L, lu, lv [3]float32, cone float32, S int, t0 time.Time) {
	H := W
	vis := make([]uint8, W*H)
	ndl := make([]uint8, W*H)
	cov := make([]uint8, W*H)
	nrm := make([]uint8, W*H*3)
	skyv := make([]uint8, W*H)
	var umax, vmax float32
	for _, t := range sc.LmTri {
		for j := 0; j < 3; j++ {
			umax = maxf(umax, t.UV[j][0])
			vmax = maxf(vmax, t.UV[j][1])
		}
	}
	us := float32(1.33331298828125)
	fmt.Printf("uv max %.4f %.4f (scaled %.4f %.4f)\n", umax, vmax, umax*us, vmax*us)
	var rays int64
	for pass := 0; pass < 2; pass++ {
		var wg sync.WaitGroup
		var next int64
		nt := len(sc.LmTri)
		for w := 0; w < runtime.NumCPU(); w++ {
			wg.Add(1)
			go func(seed int) {
				defer wg.Done()
				r := rng(uint64(seed)*0x9E3779B97F4A7C15 + 12345 + uint64(pass))
				var local int64
				for {
					i0 := int(atomic.AddInt64(&next, 256)) - 256
					if i0 >= nt {
						break
					}
					for ti := i0; ti < i0+256 && ti < nt; ti++ {
						t := &sc.LmTri[ti]
						var X, Y [3]float32
						for j := 0; j < 3; j++ {
							X[j] = t.UV[j][0] * us * float32(W)
							Y[j] = t.UV[j][1] * us * float32(H)
						}
						area := (X[1]-X[0])*(Y[2]-Y[0]) - (X[2]-X[0])*(Y[1]-Y[0])
						if abs32(area) < 1e-9 {
							continue
						}
						ng := norm(cross(sub(t.P[1], t.P[0]), sub(t.P[2], t.P[0])))
						if dot(ng, add(t.N[0], add(t.N[1], t.N[2]))) < 0 {
							ng = scale(ng, -1)
						}
						x0 := int(math.Floor(float64(min3(X[0], X[1], X[2]) - 1)))
						x1 := int(math.Ceil(float64(max3(X[0], X[1], X[2]) + 1)))
						y0 := int(math.Floor(float64(min3(Y[0], Y[1], Y[2]) - 1)))
						y1 := int(math.Ceil(float64(max3(Y[0], Y[1], Y[2]) + 1)))
						if x0 < 0 {
							x0 = 0
						}
						if y0 < 0 {
							y0 = 0
						}
						if x1 > W-1 {
							x1 = W - 1
						}
						if y1 > H-1 {
							y1 = H - 1
						}
						// edge lengths for distance test
						var el [3]float32
						for j := 0; j < 3; j++ {
							a, b := (j+1)%3, (j+2)%3
							el[j] = float32(math.Hypot(float64(X[b]-X[a]), float64(Y[b]-Y[a])))
						}
						bary := func(px, py float32) [3]float32 {
							w0 := ((X[1]-px)*(Y[2]-py) - (X[2]-px)*(Y[1]-py)) / area
							w1 := ((X[2]-px)*(Y[0]-py) - (X[0]-px)*(Y[2]-py)) / area
							return [3]float32{w0, w1, 1 - w0 - w1}
						}
						for y := y0; y <= y1; y++ {
							for x := x0; x <= x1; x++ {
								o := y*W + x
								b := bary(float32(x)+0.5, float32(y)+0.5)
								inside := b[0] >= 0 && b[1] >= 0 && b[2] >= 0
								if pass == 0 && !inside {
									continue
								}
								if pass == 1 {
									if cov[o] != 0 {
										continue
									}
									// within ~0.75 texel of the triangle?
									okd := true
									for j := 0; j < 3; j++ {
										if b[j]*abs32(area)/el[j] < -0.75 {
											okd = false
										}
									}
									if !okd {
										continue
									}
								}
								// shading normal at center
								nc := norm(add(scale(t.N[0], b[0]), add(scale(t.N[1], b[1]), scale(t.N[2], b[2]))))
								nd := dot(nc, L)
								hits := 0
								if dot(ng, L) > 0 && nd > -0.05 {
									for s := 0; s < S; s++ {
										bb := bary(float32(x)+r.f(), float32(y)+r.f())
										sum := float32(0)
										for j := 0; j < 3; j++ {
											if bb[j] < 0 {
												bb[j] = 0
											}
											sum += bb[j]
										}
										if sum <= 0 {
											bb = [3]float32{1.0 / 3, 1.0 / 3, 1.0 / 3}
											sum = 1
										}
										p := add(scale(t.P[0], bb[0]/sum), add(scale(t.P[1], bb[1]/sum), scale(t.P[2], bb[2]/sum)))
										d := coneSample(L, lu, lv, cone, &r)
										org := add(p, add(scale(ng, 1.0), scale(d, 0.5)))
										if !bvh.Occluded(org, d, 80000) {
											hits++
										}
										local++
									}
								}
								vis[o] = uint8((hits*255 + S/2) / S)
								if skyRays > 0 {
									pc := add(scale(t.P[0], b[0]), add(scale(t.P[1], b[1]), scale(t.P[2], b[2])))
									gu, gv := basis(ng)
									sh := 0
									for s := 0; s < skyRays; s++ {
										r1, r2 := r.f(), r.f()
										rr := float32(math.Sqrt(float64(r1)))
										ph := 2 * math.Pi * float64(r2)
										d := norm(add(scale(ng, float32(math.Sqrt(float64(1-r1)))), add(scale(gu, rr*float32(math.Cos(ph))), scale(gv, rr*float32(math.Sin(ph))))))
										if !bvh.Occluded(add(pc, scale(ng, 1.0)), d, 80000) {
											sh++
										}
									}
									skyv[o] = uint8((sh*255 + skyRays/2) / skyRays)
								}
								if nd < 0 {
									nd = 0
								}
								ndl[o] = uint8(nd*255 + 0.5)
								cov[o] = uint8(1 + pass)
								nrm[o*3] = uint8(nc[0]*127 + 128)
								nrm[o*3+1] = uint8(nc[1]*127 + 128)
								nrm[o*3+2] = uint8(nc[2]*127 + 128)
							}
						}
					}
				}
				atomic.AddInt64(&rays, local)
			}(w)
		}
		wg.Wait()
		fmt.Printf("[%.1fs] pass %d done, rays %d\n", time.Since(t0).Seconds(), pass, rays)
	}
	os.MkdirAll(out, 0o755)
	os.WriteFile(out+"/vis.u8", vis, 0o644)
	os.WriteFile(out+"/ndl.u8", ndl, 0o644)
	os.WriteFile(out+"/cov.u8", cov, 0o644)
	os.WriteFile(out+"/nrm.u8", nrm, 0o644)
	if skyRays > 0 {
		os.WriteFile(out+"/sky.u8", skyv, 0o644)
	}
	n := 0
	for _, c := range cov {
		if c != 0 {
			n++
		}
	}
	fmt.Printf("covered texels %d (%.1f%%)\n", n, 100*float64(n)/float64(W*H))
}

func bakePoints(bvh *BVH, in, out string, L, lu, lv [3]float32, cone float32, S, skyN int, t0 time.Time) {
	raw, err := os.ReadFile(in)
	if err != nil {
		fmt.Println(err)
		os.Exit(1)
	}
	n := len(raw) / 12
	res := make([]uint8, n*2)
	var wg sync.WaitGroup
	var next int64
	for w := 0; w < runtime.NumCPU(); w++ {
		wg.Add(1)
		go func(seed int) {
			defer wg.Done()
			r := rng(uint64(seed)*0x9E3779B97F4A7C15 + 777)
			for {
				i := int(atomic.AddInt64(&next, 1)) - 1
				if i >= n {
					return
				}
				p := [3]float32{f32(raw[i*12:]), f32(raw[i*12+4:]), f32(raw[i*12+8:])}
				hits := 0
				for s := 0; s < S; s++ {
					// jitter the probe position a little (probes sit in a grid; avoid single-ray aliasing)
					j := [3]float32{(r.f() - 0.5) * 24, (r.f() - 0.5) * 24, (r.f() - 0.5) * 24}
					d := coneSample(L, lu, lv, cone, &r)
					if !bvh.Occluded(add(p, j), d, 80000) {
						hits++
					}
				}
				res[i*2] = uint8((hits*255 + S/2) / S)
				if skyN > 0 {
					up := [3]float32{0, 0, 1}
					u, v := basis(up)
					sh := 0
					for s := 0; s < skyN; s++ {
						// cosine-weighted upper hemisphere
						r1, r2 := r.f(), r.f()
						rr := float32(math.Sqrt(float64(r1)))
						ph := 2 * math.Pi * float64(r2)
						d := add(scale(up, float32(math.Sqrt(float64(1-r1)))), add(scale(u, rr*float32(math.Cos(ph))), scale(v, rr*float32(math.Sin(ph)))))
						if !bvh.Occluded(p, norm(d), 80000) {
							sh++
						}
					}
					res[i*2+1] = uint8((sh*255 + skyN/2) / skyN)
				}
			}
		}(w)
	}
	wg.Wait()
	os.WriteFile(out, res, 0o644)
	_ = binary.LittleEndian
	fmt.Printf("[%.1fs] points %d done\n", time.Since(t0).Seconds(), n)
}
