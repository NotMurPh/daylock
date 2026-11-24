package main

// Scalar port of the meshoptimizer vertex/index decoders (MIT license, (c) Arseny Kapoulkine).

import (
	"encoding/binary"
	"errors"
	"math/bits"
)

const (
	kByteGroupSize        = 16
	kByteGroupDecodeLimit = 24
)

var kBitsV0 = []int{0, 2, 4, 8}
var kBitsV1 = []int{0, 1, 2, 4, 8}

func vertexBlockSize(vsize int) int {
	r := (8192 / vsize) &^ (kByteGroupSize - 1)
	if r < 256 {
		return r
	}
	return 256
}

func decodeBytesGroup(data []byte, p int, out []byte, b int) int {
	switch b {
	case 0:
		for i := 0; i < 16; i++ {
			out[i] = 0
		}
		return p
	case 1:
		dv := p + 2
		o := 0
		for g := 0; g < 2; g++ {
			by := bits.Reverse8(data[p+g])
			for k := 0; k < 8; k++ {
				enc := by >> 7
				by <<= 1
				if enc == 1 {
					out[o] = data[dv]
					dv++
				} else {
					out[o] = enc
				}
				o++
			}
		}
		return dv
	case 2:
		dv := p + 4
		o := 0
		for g := 0; g < 4; g++ {
			by := data[p+g]
			for k := 0; k < 4; k++ {
				enc := by >> 6
				by <<= 2
				if enc == 3 {
					out[o] = data[dv]
					dv++
				} else {
					out[o] = enc
				}
				o++
			}
		}
		return dv
	case 4:
		dv := p + 8
		o := 0
		for g := 0; g < 8; g++ {
			by := data[p+g]
			for k := 0; k < 2; k++ {
				enc := by >> 4
				by <<= 4
				if enc == 15 {
					out[o] = data[dv]
					dv++
				} else {
					out[o] = enc
				}
				o++
			}
		}
		return dv
	default:
		copy(out[:16], data[p:p+16])
		return p + 16
	}
}

func decodeBytes(data []byte, p, end int, out []byte, n int, bitsTab []int) (int, error) {
	hs := (n/kByteGroupSize + 3) / 4
	if end-p < hs {
		return 0, errors.New("short header")
	}
	h := p
	p += hs
	for i := 0; i < n; i += kByteGroupSize {
		if end-p < kByteGroupDecodeLimit {
			return 0, errors.New("short group")
		}
		ho := i / kByteGroupSize
		bk := int(data[h+ho/4]>>((ho%4)*2)) & 3
		p = decodeBytesGroup(data, p, out[i:], bitsTab[bk])
	}
	return p, nil
}

func unzig(v uint32, bitsN uint) uint32 {
	mask := uint32(1)<<bitsN - 1
	if bitsN == 32 {
		mask = 0xffffffff
	}
	return ((0 - (v & 1)) ^ (v >> 1)) & mask
}

func decodeDeltas(buf []byte, target []byte, vcount, vsize int, last []byte, tsize int, xor bool, rot int) {
	bo := 0
	for k := 0; k < 4; k += tsize {
		vo := k
		var p uint32
		for j := 0; j < tsize; j++ {
			p |= uint32(last[k+j]) << (8 * j)
		}
		for i := 0; i < vcount; i++ {
			var v uint32
			for j := 0; j < tsize; j++ {
				v |= uint32(buf[bo+i+vcount*j]) << (8 * j)
			}
			if xor {
				v = bits.RotateLeft32(v, rot) ^ p
			} else {
				v = unzig(v, uint(tsize*8)) + p
				if tsize < 4 {
					v &= uint32(1)<<(tsize*8) - 1
				}
			}
			for j := 0; j < tsize; j++ {
				target[vo+j] = byte(v >> (8 * j))
			}
			p = v
			vo += vsize
		}
		bo += vcount * tsize
	}
}

func decodeVertexBuffer(dst []byte, count, vsize int, data []byte) error {
	if len(data) < 1 || data[0]&0xf0 != 0xa0 {
		return errors.New("bad vertex header")
	}
	version := int(data[0] & 0x0f)
	if version > 1 {
		return errors.New("vertex version")
	}
	tail := vsize
	tmin := 32
	if version == 1 {
		tail += vsize / 4
		tmin = 24
	}
	tpad := tail
	if tpad < tmin {
		tpad = tmin
	}
	end := len(data)
	last := make([]byte, 256)
	copy(last, data[end-tail:end-tail+vsize])
	channels := data[end-tail+vsize : end]
	bs := vertexBlockSize(vsize)
	p := 1
	buffer := make([]byte, 256*4+32)
	for off := 0; off < count; off += bs {
		vc := bs
		if off+bs > count {
			vc = count - off
		}
		aligned := (vc + 15) &^ 15
		csize := 0
		if version == 1 {
			csize = vsize / 4
		}
		control := data[p : p+csize]
		p += csize
		target := dst[off*vsize:]
		for k := 0; k < vsize; k += 4 {
			var cb byte
			if version == 1 {
				cb = control[k/4]
			}
			for j := 0; j < 4; j++ {
				ctrl := int(cb>>(j*2)) & 3
				switch ctrl {
				case 3:
					copy(buffer[j*vc:j*vc+vc], data[p:p+vc])
					p += vc
				case 2:
					for i := 0; i < vc; i++ {
						buffer[j*vc+i] = 0
					}
				default:
					tab := kBitsV0
					if version == 1 {
						tab = kBitsV1[ctrl:]
					}
					var err error
					p, err = decodeBytes(data, p, end, buffer[j*vc:], aligned, tab)
					if err != nil {
						return err
					}
				}
			}
			ch := 0
			if version == 1 {
				ch = int(channels[k/4])
			}
			switch ch & 3 {
			case 0:
				decodeDeltas(buffer, target[k:], vc, vsize, last[k:], 1, false, 0)
			case 1:
				decodeDeltas(buffer, target[k:], vc, vsize, last[k:], 2, false, 0)
			case 2:
				decodeDeltas(buffer, target[k:], vc, vsize, last[k:], 4, true, (32-(ch>>4))&31)
			default:
				return errors.New("bad channel")
			}
		}
		copy(last[:vsize], target[vsize*(vc-1):vsize*vc])
	}
	if end-p != tpad {
		return errors.New("vertex size mismatch")
	}
	return nil
}

func decodeVByte(data []byte, p *int) uint32 {
	lead := data[*p]
	*p++
	if lead < 128 {
		return uint32(lead)
	}
	r := uint32(lead & 127)
	shift := uint(7)
	for i := 0; i < 4; i++ {
		g := data[*p]
		*p++
		r |= uint32(g&127) << shift
		shift += 7
		if g < 128 {
			break
		}
	}
	return r
}

func decodeIdx(data []byte, p *int, last uint32) uint32 {
	v := decodeVByte(data, p)
	d := (v >> 1) ^ uint32(-int32(v&1))
	return last + d
}

func decodeIndexBuffer(count int, buf []byte) ([]uint32, error) {
	if len(buf) < 1+count/3+16 || buf[0]&0xf0 != 0xe0 {
		return nil, errors.New("bad index header")
	}
	version := int(buf[0] & 0x0f)
	out := make([]uint32, 0, count)
	var ef [16][2]uint32
	var vf [16]uint32
	for i := range ef {
		ef[i] = [2]uint32{0xffffffff, 0xffffffff}
		vf[i] = 0xffffffff
	}
	efo, vfo := 0, 0
	var next, last uint32
	fecmax := 15
	if version >= 1 {
		fecmax = 13
	}
	code := 1
	codeEnd := code + count/3
	data := codeEnd
	safeEnd := len(buf) - 16
	aux := buf[safeEnd:]
	pushE := func(a, b uint32) { ef[efo] = [2]uint32{a, b}; efo = (efo + 1) & 15 }
	pushV := func(v uint32, cond bool) {
		vf[vfo] = v
		if cond {
			vfo = (vfo + 1) & 15
		}
	}
	for code < codeEnd {
		ct := buf[code]
		code++
		if ct < 0xf0 {
			fe := int(ct >> 4)
			e := ef[(efo-1-fe)&15]
			a, b := e[0], e[1]
			var c uint32
			fec := int(ct & 15)
			if fec < fecmax {
				cf := vf[(vfo-1-fec)&15]
				if fec == 0 {
					c = next
					next++
				} else {
					c = cf
				}
				pushV(c, fec == 0)
			} else {
				if fec != 15 {
					c = last + uint32(fec*2-27)
				} else {
					c = decodeIdx(buf, &data, last)
				}
				last = c
				pushV(c, true)
			}
			pushE(c, b)
			pushE(a, c)
			out = append(out, a, b, c)
		} else if ct < 0xfe {
			ca := aux[ct&15]
			feb := int(ca >> 4)
			fec := int(ca & 15)
			a := next
			next++
			bf := vf[(vfo-feb)&15]
			b := bf
			if feb == 0 {
				b = next
				next++
			}
			cf := vf[(vfo-fec)&15]
			c := cf
			if fec == 0 {
				c = next
				next++
			}
			out = append(out, a, b, c)
			pushV(a, true)
			pushV(b, feb == 0)
			pushV(c, fec == 0)
			pushE(b, a)
			pushE(c, b)
			pushE(a, c)
		} else {
			ca := buf[data]
			data++
			fea := 15
			if ct == 0xfe {
				fea = 0
			}
			feb := int(ca >> 4)
			fec := int(ca & 15)
			if ca == 0 {
				next = 0
			}
			var a, b, c uint32
			if fea == 0 {
				a = next
				next++
			}
			if feb == 0 {
				b = next
				next++
			} else {
				b = vf[(vfo-feb)&15]
			}
			if fec == 0 {
				c = next
				next++
			} else {
				c = vf[(vfo-fec)&15]
			}
			if fea == 15 {
				a = decodeIdx(buf, &data, last)
				last = a
			}
			if feb == 15 {
				b = decodeIdx(buf, &data, last)
				last = b
			}
			if fec == 15 {
				c = decodeIdx(buf, &data, last)
				last = c
			}
			out = append(out, a, b, c)
			pushV(a, true)
			pushV(b, feb == 0 || feb == 15)
			pushV(c, fec == 0 || fec == 15)
			pushE(b, a)
			pushE(c, b)
			pushE(a, c)
		}
	}
	if data != safeEnd {
		return out, errors.New("index size mismatch")
	}
	return out, nil
}

func rawIndices(buf []byte, count, isize int) []uint32 {
	out := make([]uint32, count)
	for i := 0; i < count; i++ {
		if isize == 2 {
			out[i] = uint32(binary.LittleEndian.Uint16(buf[i*2:]))
		} else {
			out[i] = binary.LittleEndian.Uint32(buf[i*4:])
		}
	}
	return out
}
