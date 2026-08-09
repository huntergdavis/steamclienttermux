//go:build windows && amd64

// cpuid-probe compares the raw x86 CPUID feature bits exposed to a Windows
// process with the corresponding Win32 processor-feature queries.
package main

import (
	"encoding/binary"
	"fmt"
	"os"
	"runtime"
	"strings"
	"syscall"
)

func cpuid(eax, ecx uint32) (a, b, c, d uint32)

func processorFeature(proc *syscall.LazyProc, feature uintptr) uintptr {
	available, _, _ := proc.Call(feature)
	return available
}

func main() {
	var output strings.Builder

	maxLeaf, vendorB, vendorC, vendorD := cpuid(0, 0)
	vendor := make([]byte, 12)
	binary.LittleEndian.PutUint32(vendor[0:4], vendorB)
	binary.LittleEndian.PutUint32(vendor[4:8], vendorD)
	binary.LittleEndian.PutUint32(vendor[8:12], vendorC)

	eax, ebx, ecx, edx := cpuid(1, 0)
	fmt.Fprintf(&output, "goarch=%s vendor=%q max_leaf=%#x\n", runtime.GOARCH, vendor, maxLeaf)
	fmt.Fprintf(&output, "cpuid.1 eax=%08x ebx=%08x ecx=%08x edx=%08x\n", eax, ebx, ecx, edx)
	fmt.Fprintf(&output, "cpuid.de=%t cpuid.pse=%t cpuid.sse=%t cpuid.sse2=%t\n",
		edx&(1<<2) != 0,
		edx&(1<<3) != 0,
		edx&(1<<25) != 0,
		edx&(1<<26) != 0)

	maxExtended, _, _, _ := cpuid(0x80000000, 0)
	if maxExtended >= 0x80000001 {
		_, _, _, extendedEDX := cpuid(0x80000001, 0)
		fmt.Fprintf(&output, "cpuid.80000001.edx=%08x cpuid.page1gb=%t\n",
			extendedEDX, extendedEDX&(1<<26) != 0)
	}

	isProcessorFeaturePresent := syscall.NewLazyDLL("kernel32.dll").NewProc("IsProcessorFeaturePresent")
	// WinNT.h: PF_XMMI_INSTRUCTIONS_AVAILABLE=6 and
	// PF_XMMI64_INSTRUCTIONS_AVAILABLE=10.
	fmt.Fprintf(&output, "win32.sse=%d win32.sse2=%d\n",
		processorFeature(isProcessorFeaturePresent, 6),
		processorFeature(isProcessorFeaturePresent, 10))

	fmt.Print(output.String())
	if len(os.Args) > 1 {
		if err := os.WriteFile(os.Args[1], []byte(output.String()), 0600); err != nil {
			fmt.Fprintf(os.Stderr, "cpuid-probe: write %q: %v\n", os.Args[1], err)
			os.Exit(1)
		}
	}
}
