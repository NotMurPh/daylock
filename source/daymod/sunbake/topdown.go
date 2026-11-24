package main

import (
	"fmt"
	"os"
	"runtime"
	"sync"
)

// top-down render: height-shaded + sun shadow, writes PGM
func topdown(bvh *BVH, L [3]float32, out string) {
	const N = 2048
	x0, x1, y0, y1 := float32(-10500), float32(10500), float32(-11500), float32(9500)
	img := make([]byte, N*N)
	var wg sync.WaitGroup
	rows := make(chan int, N)
	for i := 0; i < N; i++ {
		rows <- i
	}
	close(rows)
	for w := 0; w < runtime.NumCPU(); w++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			for r := range rows {
				for c := 0; c < N; c++ {
					x := x0 + (x1-x0)*(float32(c)+0.5)/N
					y := y1 - (y1-y0)*(float32(r)+0.5)/N
					o := [3]float32{x, y, 6000}
					d := [3]float32{0, 0, -1}
					id, t := bvh.Closest(o, d, 20000)
					if id < 0 {
						img[r*N+c] = 0
						continue
					}
					p := add(o, scale(d, t-1))
					v := byte(70)
					if !bvh.Occluded(p, L, 80000) {
						v = 230
					}
					img[r*N+c] = v
				}
			}
		}()
	}
	wg.Wait()
	f, _ := os.Create(out)
	fmt.Fprintf(f, "P5\n%d %d\n255\n", N, N)
	f.Write(img)
	f.Close()
}
