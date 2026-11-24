package main

import (
	"fmt"
	"math"
	"os"
	"sort"
	"strconv"
	"strings"
)

// pickMode: cast a grid of rays from a camera and report which materials are hit
// (debug: find which material a surface on screen uses). arg = x,y,z,yaw0,yaw1,pitch0,pitch1 (degrees, pitch up = +)
func pickMode(bvh *BVH, sc *Scene, arg string) {
	f := strings.Split(arg, ",")
	v := make([]float64, len(f))
	for i, x := range f {
		v[i], _ = strconv.ParseFloat(strings.TrimSpace(x), 64)
	}
	o := [3]float32{float32(v[0]), float32(v[1]), float32(v[2])}
	cnt := map[int32]int{}
	dsum := map[int32]float64{}
	for yaw := v[3]; yaw <= v[4]; yaw += 0.5 {
		for pit := v[5]; pit <= v[6]; pit += 0.5 {
			a, e := yaw*math.Pi/180, pit*math.Pi/180
			d := [3]float32{float32(math.Cos(e) * math.Cos(a)), float32(math.Cos(e) * math.Sin(a)), float32(math.Sin(e))}
			id, t := bvh.Closest(o, d, 80000)
			if id >= 0 {
				m := sc.CastMat[id]
				cnt[m]++
				dsum[m] += float64(t)
			}
		}
	}
	ids := make([]int32, 0, len(cnt))
	for k := range cnt {
		ids = append(ids, k)
	}
	sort.Slice(ids, func(i, j int) bool { return cnt[ids[i]] > cnt[ids[j]] })
	for _, k := range ids {
		fmt.Printf("%6d  dist %6.0f  %s\n", cnt[k], dsum[k]/float64(cnt[k]), sc.Mats[k])
	}
}

// drawTag: with SUNBAKE_DRAWIDS=1 the material label carries the draw call index (for pick debugging)
func drawTag(di int) string {
	if os.Getenv("SUNBAKE_DRAWIDS") == "1" {
		return " #" + strconv.Itoa(di)
	}
	return ""
}

// boundsMode: world bounding box + triangle count of every caster label containing `filter`
func boundsMode(sc *Scene, filter string) {
	type bb struct {
		mn, mx [3]float32
		n      int
	}
	res := map[int32]*bb{}
	for i, t := range sc.Cast {
		id := sc.CastMat[i]
		if !strings.Contains(sc.Mats[id], filter) {
			continue
		}
		b := res[id]
		if b == nil {
			b = &bb{mn: [3]float32{1e9, 1e9, 1e9}, mx: [3]float32{-1e9, -1e9, -1e9}}
			res[id] = b
		}
		for k := 0; k < 9; k++ {
			a := k % 3
			if t[k] < b.mn[a] {
				b.mn[a] = t[k]
			}
			if t[k] > b.mx[a] {
				b.mx[a] = t[k]
			}
		}
		b.n++
	}
	for id, b := range res {
		fmt.Printf("%-110s tris %6d  min %6.0f %6.0f %6.0f  max %6.0f %6.0f %6.0f\n", sc.Mats[id], b.n, b.mn[0], b.mn[1], b.mn[2], b.mx[0], b.mx[1], b.mx[2])
	}
}

// lmMask: mark the lightmap texels covered by lightmapped triangles whose draw label contains one of the
// comma-separated filters (1-texel dilation), write <out> as W*W u8 (255 = covered)
func lmMask(sc *Scene, filters string, out string, W int) {
	fs := strings.Split(filters, ",")
	sel := map[int32]bool{}
	for id, l := range sc.LmLabels {
		for _, f := range fs {
			if f != "" && strings.Contains(l, strings.TrimSpace(f)) {
				sel[int32(id)] = true
				fmt.Println("mask:", l)
			}
		}
	}
	lmRaster(sc, func(t *LmTri) bool { return sel[t.Lab] }, out, W)
}

// lmBox: like lmMask, but selects lightmapped triangles whose centroid is inside the box x0,y0,z0,x1,y1,z1
func lmBox(sc *Scene, box string, out string, W int) {
	f := strings.Split(box, ",")
	v := make([]float32, 6)
	for i := range v {
		x, _ := strconv.ParseFloat(strings.TrimSpace(f[i]), 64)
		v[i] = float32(x)
	}
	lmRaster(sc, func(t *LmTri) bool {
		c := scale(add(t.P[0], add(t.P[1], t.P[2])), 1.0/3)
		return c[0] >= v[0] && c[1] >= v[1] && c[2] >= v[2] && c[0] <= v[3] && c[1] <= v[4] && c[2] <= v[5]
	}, out, W)
}

func lmRaster(sc *Scene, keep func(t *LmTri) bool, out string, W int) {
	us := float32(1.33331298828125)
	m := make([]uint8, W*W)
	n := 0
	for i := range sc.LmTri {
		t := &sc.LmTri[i]
		if !keep(t) {
			continue
		}
		var X, Y [3]float32
		for j := 0; j < 3; j++ {
			X[j] = t.UV[j][0] * us * float32(W)
			Y[j] = t.UV[j][1] * us * float32(W)
		}
		area := (X[1]-X[0])*(Y[2]-Y[0]) - (X[2]-X[0])*(Y[1]-Y[0])
		if abs32(area) < 1e-9 {
			continue
		}
		x0, x1 := int(min3(X[0], X[1], X[2]))-1, int(max3(X[0], X[1], X[2]))+1
		y0, y1 := int(min3(Y[0], Y[1], Y[2]))-1, int(max3(Y[0], Y[1], Y[2]))+1
		for y := y0; y <= y1; y++ {
			for x := x0; x <= x1; x++ {
				if x < 0 || y < 0 || x >= W || y >= W {
					continue
				}
				in := false
				for _, d := range [][2]float32{{0.5, 0.5}, {-0.5, 0.5}, {1.5, 0.5}, {0.5, -0.5}, {0.5, 1.5}} {
					px, py := float32(x)+d[0], float32(y)+d[1]
					w0 := ((X[1]-px)*(Y[2]-py) - (X[2]-px)*(Y[1]-py)) / area
					w1 := ((X[2]-px)*(Y[0]-py) - (X[0]-px)*(Y[2]-py)) / area
					if w0 >= 0 && w1 >= 0 && 1-w0-w1 >= 0 {
						in = true
						break
					}
				}
				if in && m[y*W+x] == 0 {
					m[y*W+x] = 255
					n++
				}
			}
		}
	}
	fmt.Println("mask texels", n)
	if err := os.WriteFile(out, m, 0o644); err != nil {
		fmt.Println(err)
	}
}

// samplesMode: print up to 60 evenly spaced triangle centroids + face normals (x y z nx ny nz) per label matching filter
func samplesMode(sc *Scene, filter string) {
	byLab := map[int32][]int{}
	for i := range sc.Cast {
		id := sc.CastMat[i]
		if strings.Contains(sc.Mats[id], filter) {
			byLab[id] = append(byLab[id], i)
		}
	}
	for id, tris := range byLab {
		fmt.Println("label", sc.Mats[id], len(tris))
		step := len(tris)/60 + 1
		for k := 0; k < len(tris); k += step {
			t := sc.Cast[tris[k]]
			a := [3]float32{t[0], t[1], t[2]}
			b := [3]float32{t[3], t[4], t[5]}
			c := [3]float32{t[6], t[7], t[8]}
			n := norm(cross(sub(b, a), sub(c, a)))
			p := scale(add(a, add(b, c)), 1.0/3)
			fmt.Printf("s %.0f %.0f %.0f %.3f %.3f %.3f\n", p[0], p[1], p[2], n[0], n[1], n[2])
		}
	}
}

// sunScan: for each box "name:x0,y0,z0,x1,y1,z1;..." sample upward lightmapped triangles inside it and print the
// fraction that sees the sun for a grid of sun directions (choosing a sun that lights several rooms)
func sunScan(bvh *BVH, sc *Scene, arg string) {
	type room struct {
		name string
		pts  [][3]float32
	}
	var rooms []room
	for _, part := range strings.Split(arg, ";") {
		nv := strings.SplitN(part, ":", 2)
		f := strings.Split(nv[1], ",")
		v := make([]float32, 6)
		for i := range v {
			x, _ := strconv.ParseFloat(strings.TrimSpace(f[i]), 64)
			v[i] = float32(x)
		}
		r := room{name: nv[0]}
		for i := range sc.LmTri {
			t := &sc.LmTri[i]
			c := scale(add(t.P[0], add(t.P[1], t.P[2])), 1.0/3)
			if c[0] < v[0] || c[1] < v[1] || c[2] < v[2] || c[0] > v[3] || c[1] > v[4] || c[2] > v[5] {
				continue
			}
			ng := norm(cross(sub(t.P[1], t.P[0]), sub(t.P[2], t.P[0])))
			if dot(ng, add(t.N[0], add(t.N[1], t.N[2]))) < 0 {
				ng = scale(ng, -1)
			}
			if ng[2] > 0.9 {
				r.pts = append(r.pts, add(c, scale(ng, 2)))
			}
		}
		fmt.Println("room", r.name, "floor samples", len(r.pts))
		rooms = append(rooms, r)
	}
	for el := 15.0; el <= 65; el += 5 {
		for az := 0.0; az < 360; az += 10 {
			L := sunDir(az, el)
			fmt.Printf("az %3.0f el %2.0f", az, el)
			for _, r := range rooms {
				lit, n := 0, 0
				for k := 0; k < len(r.pts); k += 1 + len(r.pts)/4000 {
					n++
					if !bvh.Occluded(r.pts[k], L, 80000) {
						lit++
					}
				}
				fmt.Printf("  %s %5.1f%%", r.name, 100*float64(lit)/float64(max(n, 1)))
			}
			fmt.Println()
		}
	}
}
