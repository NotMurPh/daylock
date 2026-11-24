package main

import (
	"fmt"
	"math"
)

func lmAt(bvh *BVH, sc *Scene, c [3]float32, rad float32) {
	n := 0
	for i := range sc.LmTri {
		t := &sc.LmTri[i]
		p := scale(add(t.P[0], add(t.P[1], t.P[2])), 1.0/3)
		d := sub(p, c)
		if float32(math.Sqrt(float64(dot(d, d)))) > rad {
			continue
		}
		ng := norm(cross(sub(t.P[1], t.P[0]), sub(t.P[2], t.P[0])))
		nv := norm(add(t.N[0], add(t.N[1], t.N[2])))
		// sky test straight along the vertex normal and straight up
		idA, tA := bvh.Closest(add(p, scale(nv, 1)), nv, 80000)
		idU, tU := bvh.Closest(add(p, [3]float32{0, 0, 1}), [3]float32{0, 0, 1}, 80000)
		u := (t.UV[0][0] + t.UV[1][0] + t.UV[2][0]) / 3 * 1.33331298828125 * 8192
		v := (t.UV[0][1] + t.UV[1][1] + t.UV[2][1]) / 3 * 1.33331298828125 * 8192
		fmt.Printf("p %6.0f %6.0f %5.0f ng %5.2f %5.2f %5.2f nv %5.2f %5.2f %5.2f texel %5.0f %5.0f | alongN hit %d %.0f | up hit %d %.0f\n",
			p[0], p[1], p[2], ng[0], ng[1], ng[2], nv[0], nv[1], nv[2], u, v, idA, tA, idU, tU)
		n++
		if n > 25 {
			return
		}
	}
}
