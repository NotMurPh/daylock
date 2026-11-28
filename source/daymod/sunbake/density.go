package main

import (
	"fmt"
	"math"
	"sort"
)

// lmDensity: world units per lightmap texel for upward-facing lightmapped triangles (floors), by map region.
func lmDensity(sc *Scene, W int) {
	us := float32(1.33331298828125)
	var d []float64
	var wsum float64
	for i := range sc.LmTri {
		t := &sc.LmTri[i]
		ng := norm(cross(sub(t.P[1], t.P[0]), sub(t.P[2], t.P[0])))
		if ng[2] < 0.9 && ng[2] > -0.9 {
			continue
		}
		wa := 0.5 * float64(vlen(cross(sub(t.P[1], t.P[0]), sub(t.P[2], t.P[0]))))
		var X, Y [3]float32
		for j := 0; j < 3; j++ {
			X[j] = t.UV[j][0] * us * float32(W)
			Y[j] = t.UV[j][1] * us * float32(W)
		}
		ta := math.Abs(float64(0.5 * ((X[1]-X[0])*(Y[2]-Y[0]) - (X[2]-X[0])*(Y[1]-Y[0]))))
		if ta < 1e-6 || wa < 1 {
			continue
		}
		u := math.Sqrt(wa / ta)
		// weight by world area: repeat proportional
		n := int(wa/1000) + 1
		for k := 0; k < n; k++ {
			d = append(d, u)
		}
		wsum += wa
	}
	sort.Float64s(d)
	q := func(p float64) float64 { return d[int(p*float64(len(d)-1))] }
	fmt.Printf("floor/ceiling world units per texel (area-weighted): p10 %.1f p25 %.1f p50 %.1f p75 %.1f p90 %.1f\n", q(.1), q(.25), q(.5), q(.75), q(.9))
}

func vlen(a [3]float32) float32 { return float32(math.Sqrt(float64(dot(a, a)))) }
