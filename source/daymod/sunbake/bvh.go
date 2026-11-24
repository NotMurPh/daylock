package main

import (
	"math"
	"sync"
	"sync/atomic"
)

type Node struct {
	Min, Max [3]float32
	Left     int32 // child index (inner) or first triangle (leaf)
	Count    int32 // 0 = inner
}

type BVH struct {
	Nodes []Node
	Tris  [][9]float32
	Idx   []int32
}

type bref struct {
	min, max, c [3]float32
}

func buildBVH(tris [][9]float32) *BVH {
	n := len(tris)
	refs := make([]bref, n)
	idx := make([]int32, n)
	for i, t := range tris {
		var r bref
		for k := 0; k < 3; k++ {
			r.min[k] = min3(t[k], t[3+k], t[6+k])
			r.max[k] = max3(t[k], t[3+k], t[6+k])
			r.c[k] = (r.min[k] + r.max[k]) * 0.5
		}
		refs[i] = r
		idx[i] = int32(i)
	}
	b := &BVH{Nodes: make([]Node, 2*n+64)}
	var cnt int32 = 1
	var wg sync.WaitGroup
	sem := make(chan struct{}, 32)
	var build func(ni int32, lo, hi int, depth int)
	build = func(ni int32, lo, hi int, depth int) {
		nd := &b.Nodes[ni]
		var bmin, bmax, cmin, cmax [3]float32
		for k := 0; k < 3; k++ {
			bmin[k], cmin[k] = math.MaxFloat32, math.MaxFloat32
			bmax[k], cmax[k] = -math.MaxFloat32, -math.MaxFloat32
		}
		for i := lo; i < hi; i++ {
			r := &refs[idx[i]]
			for k := 0; k < 3; k++ {
				bmin[k] = minf(bmin[k], r.min[k])
				bmax[k] = maxf(bmax[k], r.max[k])
				cmin[k] = minf(cmin[k], r.c[k])
				cmax[k] = maxf(cmax[k], r.c[k])
			}
		}
		nd.Min, nd.Max = bmin, bmax
		count := hi - lo
		if count <= 4 {
			nd.Left, nd.Count = int32(lo), int32(count)
			return
		}
		axis := 0
		ext := cmax[0] - cmin[0]
		for k := 1; k < 3; k++ {
			if cmax[k]-cmin[k] > ext {
				axis, ext = k, cmax[k]-cmin[k]
			}
		}
		mid := -1
		if ext > 0 {
			// binned SAH
			const NB = 16
			var bc [NB]int
			var bb [NB][6]float32
			for i := range bb {
				bb[i] = [6]float32{math.MaxFloat32, math.MaxFloat32, math.MaxFloat32, -math.MaxFloat32, -math.MaxFloat32, -math.MaxFloat32}
			}
			sc := float32(NB) / ext * 0.9999
			for i := lo; i < hi; i++ {
				r := &refs[idx[i]]
				bi := int((r.c[axis] - cmin[axis]) * sc)
				bc[bi]++
				for k := 0; k < 3; k++ {
					bb[bi][k] = minf(bb[bi][k], r.min[k])
					bb[bi][3+k] = maxf(bb[bi][3+k], r.max[k])
				}
			}
			var lArea [NB]float32
			var lCnt [NB]int
			acc := [6]float32{math.MaxFloat32, math.MaxFloat32, math.MaxFloat32, -math.MaxFloat32, -math.MaxFloat32, -math.MaxFloat32}
			c := 0
			for i := 0; i < NB-1; i++ {
				acc = merge6(acc, bb[i])
				c += bc[i]
				lArea[i], lCnt[i] = area6(acc), c
			}
			acc = [6]float32{math.MaxFloat32, math.MaxFloat32, math.MaxFloat32, -math.MaxFloat32, -math.MaxFloat32, -math.MaxFloat32}
			c = 0
			best, bestCost := -1, float32(math.MaxFloat32)
			for i := NB - 1; i > 0; i-- {
				acc = merge6(acc, bb[i])
				c += bc[i]
				if lCnt[i-1] == 0 || c == 0 {
					continue
				}
				cost := lArea[i-1]*float32(lCnt[i-1]) + area6(acc)*float32(c)
				if cost < bestCost {
					best, bestCost = i, cost
				}
			}
			if best > 0 {
				i, j := lo, hi-1
				for i <= j {
					if int((refs[idx[i]].c[axis]-cmin[axis])*sc) < best {
						i++
					} else {
						idx[i], idx[j] = idx[j], idx[i]
						j--
					}
				}
				mid = i
			}
		}
		if mid <= lo || mid >= hi {
			mid = (lo + hi) / 2
		}
		left := atomic.AddInt32(&cnt, 2) - 2
		nd.Left, nd.Count = left, 0
		if depth < 8 {
			select {
			case sem <- struct{}{}:
				wg.Add(1)
				go func() {
					defer wg.Done()
					build(left, lo, mid, depth+1)
					<-sem
				}()
				build(left+1, mid, hi, depth+1)
				return
			default:
			}
		}
		build(left, lo, mid, depth+1)
		build(left+1, mid, hi, depth+1)
	}
	build(0, 0, n, 0)
	wg.Wait()
	b.Nodes = b.Nodes[:cnt]
	b.Idx = idx
	b.Tris = make([][9]float32, n)
	for i, j := range idx {
		b.Tris[i] = tris[j]
	}
	return b
}

func merge6(a, b [6]float32) [6]float32 {
	return [6]float32{minf(a[0], b[0]), minf(a[1], b[1]), minf(a[2], b[2]), maxf(a[3], b[3]), maxf(a[4], b[4]), maxf(a[5], b[5])}
}
func area6(a [6]float32) float32 {
	if a[3] < a[0] {
		return 0
	}
	x, y, z := a[3]-a[0], a[4]-a[1], a[5]-a[2]
	return x*y + y*z + z*x
}
func minf(a, b float32) float32 {
	if a < b {
		return a
	}
	return b
}
func maxf(a, b float32) float32 {
	if a > b {
		return a
	}
	return b
}
func min3(a, b, c float32) float32 { return minf(a, minf(b, c)) }
func max3(a, b, c float32) float32 { return maxf(a, maxf(b, c)) }

// Occluded: any hit along o + t*d, t in (tmin, tmax)
func (b *BVH) Occluded(o, d [3]float32, tmax float32) bool {
	var inv [3]float32
	for k := 0; k < 3; k++ {
		if d[k] != 0 {
			inv[k] = 1 / d[k]
		} else {
			inv[k] = math.MaxFloat32
		}
	}
	var stack [96]int32
	sp := 0
	stack[sp] = 0
	sp++
	for sp > 0 {
		sp--
		nd := &b.Nodes[stack[sp]]
		// slab test
		t0, t1 := float32(0), tmax
		hit := true
		for k := 0; k < 3; k++ {
			ta := (nd.Min[k] - o[k]) * inv[k]
			tb := (nd.Max[k] - o[k]) * inv[k]
			if ta > tb {
				ta, tb = tb, ta
			}
			if ta > t0 {
				t0 = ta
			}
			if tb < t1 {
				t1 = tb
			}
			if t0 > t1 {
				hit = false
				break
			}
		}
		if !hit {
			continue
		}
		if nd.Count > 0 {
			for i := nd.Left; i < nd.Left+nd.Count; i++ {
				if rayTri(o, d, &b.Tris[i], tmax) {
					return true
				}
			}
			continue
		}
		if sp+2 > len(stack) {
			continue
		}
		stack[sp] = nd.Left
		stack[sp+1] = nd.Left + 1
		sp += 2
	}
	return false
}

func rayTri(o, d [3]float32, t *[9]float32, tmax float32) bool {
	e1 := [3]float32{t[3] - t[0], t[4] - t[1], t[5] - t[2]}
	e2 := [3]float32{t[6] - t[0], t[7] - t[1], t[8] - t[2]}
	p := cross(d, e2)
	det := dot(e1, p)
	if det > -1e-9 && det < 1e-9 {
		return false
	}
	inv := 1 / det
	s := [3]float32{o[0] - t[0], o[1] - t[1], o[2] - t[2]}
	u := dot(s, p) * inv
	if u < 0 || u > 1 {
		return false
	}
	q := cross(s, e1)
	v := dot(d, q) * inv
	if v < 0 || u+v > 1 {
		return false
	}
	tt := dot(e2, q) * inv
	return tt > 1e-3 && tt < tmax
}

// Closest: nearest hit triangle (index into original order) and distance, -1 if none
func (b *BVH) Closest(o, d [3]float32, tmax float32) (int32, float32) {
	var inv [3]float32
	for k := 0; k < 3; k++ {
		if d[k] != 0 {
			inv[k] = 1 / d[k]
		} else {
			inv[k] = math.MaxFloat32
		}
	}
	best := int32(-1)
	var stack [96]int32
	sp := 1
	for sp > 0 {
		sp--
		nd := &b.Nodes[stack[sp]]
		t0, t1 := float32(0), tmax
		hit := true
		for k := 0; k < 3; k++ {
			ta := (nd.Min[k] - o[k]) * inv[k]
			tb := (nd.Max[k] - o[k]) * inv[k]
			if ta > tb {
				ta, tb = tb, ta
			}
			if ta > t0 {
				t0 = ta
			}
			if tb < t1 {
				t1 = tb
			}
			if t0 > t1 {
				hit = false
				break
			}
		}
		if !hit {
			continue
		}
		if nd.Count > 0 {
			for i := nd.Left; i < nd.Left+nd.Count; i++ {
				if t, ok := rayTriT(o, d, &b.Tris[i], tmax); ok {
					tmax = t
					best = b.Idx[i]
				}
			}
			continue
		}
		if sp+2 > len(stack) {
			continue
		}
		stack[sp] = nd.Left
		stack[sp+1] = nd.Left + 1
		sp += 2
	}
	return best, tmax
}

func rayTriT(o, d [3]float32, t *[9]float32, tmax float32) (float32, bool) {
	e1 := [3]float32{t[3] - t[0], t[4] - t[1], t[5] - t[2]}
	e2 := [3]float32{t[6] - t[0], t[7] - t[1], t[8] - t[2]}
	p := cross(d, e2)
	det := dot(e1, p)
	if det > -1e-9 && det < 1e-9 {
		return 0, false
	}
	inv := 1 / det
	s := [3]float32{o[0] - t[0], o[1] - t[1], o[2] - t[2]}
	u := dot(s, p) * inv
	if u < 0 || u > 1 {
		return 0, false
	}
	q := cross(s, e1)
	v := dot(d, q) * inv
	if v < 0 || u+v > 1 {
		return 0, false
	}
	tt := dot(e2, q) * inv
	return tt, tt > 1e-3 && tt < tmax
}
