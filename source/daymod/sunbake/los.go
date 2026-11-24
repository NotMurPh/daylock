package main

import (
	"fmt"
	"os"
)

// los: input float32 pairs (ax ay az bx by bz)*N -> output byte per pair (1 = clear line of sight)
func losMode(bvh *BVH, in, out string) {
	raw, err := os.ReadFile(in)
	if err != nil {
		fmt.Println(err)
		os.Exit(1)
	}
	n := len(raw) / 24
	res := make([]byte, n)
	for i := 0; i < n; i++ {
		a := [3]float32{f32(raw[i*24:]), f32(raw[i*24+4:]), f32(raw[i*24+8:])}
		b := [3]float32{f32(raw[i*24+12:]), f32(raw[i*24+16:]), f32(raw[i*24+20:])}
		d := sub(b, a)
		l := float32(0)
		for _, v := range d {
			l += v * v
		}
		if l == 0 {
			res[i] = 1
			continue
		}
		dn := norm(d)
		dist := dot(d, dn)
		if !bvh.Occluded(a, dn, dist-40) { // stop 40 units short of the target (the target itself)
			res[i] = 1
		}
	}
	os.WriteFile(out, res, 0o644)
	fmt.Println("los pairs", n)
}
