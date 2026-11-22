# Measure the current array-read baseline

Run the reviewed tool from a checkout with its normal core dependencies:

```bash
python scripts/benchmark_array_reads.py --output /tmp/db-array-baseline-001
```

The output directory must be new and its parent must exist. Existing paths,
including symlinks, are refused before fixture creation. The tool creates
only synthetic data in that directory; it does not accept an existing database.
The default fixture is 1,000,000 samples by eight channels, float32, with 100
windows of 1,000 samples at a declared sampling rate of 250 Hz. Adjust these
explicitly for the machine and question being measured:

```bash
python scripts/benchmark_array_reads.py --output /tmp/db-array-small-001 \
  --samples 65536 --channels 8 --windows 12 --window-samples 512 \
  --sampling-rate 250 --seed 7
```

The comparison uses three fresh worker processes in a fixed order:

- `memory`: load the complete NumPy array before timing, then read resident slices.
- `plain`: call the current `SQLite3.load_array` for each window, then slice the
  fully decoded array from an uncompressed BLOB.
- `compressed`: the same whole-BLOB access with zlib compression level six.

This measures the current array API, not a chunked or range-read API. The full
recording must fit in memory. A small window does not prevent the SQLite modes
from decoding the whole stored array on every read. Chunked storage, recording
metadata helpers, out-of-RAM behavior and a PyTorch adapter remain separate work.
The synthetic independent normal samples are reproducible fixtures, not a model
of EEG/IMU compression or representative clinical data.

`report.json` records the input seed/shape/dtype and data hash, exact window
starts and a reference checksum, library/script hashes, Python/NumPy/SQLite/zlib
versions, platform, file sizes, worker PIDs and each result. Each worker verifies
its window checksum against the generated NumPy reference before reporting.
The first two windows cover the start and end boundaries.

Timing includes window access and checksum work. It excludes fixture creation,
connection setup and the initial resident NumPy load. Process CPU time is
reported separately. Signal-seconds per second is
`windows * window_samples / sampling_rate / elapsed_seconds`: overlapping or
repeated samples count repeatedly, so this is processed work, not unique
recording duration. The sampling rate is a declared conversion factor; it is
not inferred from the random numbers.

Peak RSS includes imports and initial loading; it is not an incremental
allocation measurement. On Linux the primary metric is `/proc/self/status`
`VmHWM`, whose [kernel definition](https://docs.kernel.org/filesystems/proc.html)
is an approximate RSS high-water mark. The report names the metric explicitly.
Raw `ru_maxrss_bytes` is retained separately: Linux preserves
[getrusage accounting across exec](https://man7.org/linux/man-pages/man2/getrusage.2.html),
so process-startup history can mask small worker differences. On macOS the
reported metric is `ru_maxrss`; unsupported/unavailable metrics are `null`.
Workers use one configured math-library thread, recorded in the input config.
These OS counters are not interchangeable allocation profiles. The NumPy
baseline is fully resident; none establishes out-of-core capability.

No cache eviction, host tuning or disk-cache reset is performed. Fixture writes
may populate the OS cache. Keep raw JSON, configuration, source identity and
machine/resource limits with any quoted result; record repeated runs as separate
new directories. Do not transfer one toy fixture's rate to another dataset or a
proposal workload. This tool publishes no benchmark or acceptance threshold.

Owning implementation: [the tool](../scripts/benchmark_array_reads.py) and
[current array loader](../src/scitex_db/_sqlite3/_SQLite3Mixins/_ArrayMixin.py).
[Real process/value/admission tests](../tests/scripts/test_benchmark_array_reads.py)
exercise all three backends, independent window checksums, actual compression
flags, rate units, separate PIDs and no-overwrite refusals. These are correctness
checks, not performance thresholds or full native/platform qualification.
