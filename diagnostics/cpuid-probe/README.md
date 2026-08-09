# FEX CPUID probe

This source-only Windows AMD64 diagnostic compares the raw CPUID feature bits
seen by a guest executable with Wine's `IsProcessorFeaturePresent` answers. It
exists to distinguish a real SSE2 omission from Burnout Paradise Remastered's
legacy CPUID check.

Build it on a host with Go installed:

```sh
GO111MODULE=off GOOS=windows GOARCH=amd64 CGO_ENABLED=0 \
  go build -trimpath -o /tmp/cpuid-probe.exe ./diagnostics/cpuid-probe
```

The probe prints CPUID leaf 1 EDX bits for Debugging Extensions (`DE`, bit 2),
Page Size Extension (`PSE`, bit 3), SSE (bit 25), and SSE2 (bit 26), followed by
the corresponding Win32 SSE/SSE2 results. An optional first argument writes the
same output to a file, which is useful when Wine stdout is unavailable.

Do not commit the generated executable. Do not replace Steam-managed FEX DLLs
to run this probe. FEX issue [#5805](https://github.com/FEX-Emu/FEX/issues/5805)
documents that Burnout checks DE rather than SSE2; merged fix
[`9365e624`](https://github.com/FEX-Emu/FEX/commit/9365e6240b3b87466753cd989d257e5c93092578)
advertises the legacy bits expected by the game.
