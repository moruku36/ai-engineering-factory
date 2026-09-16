# Compatibility Matrix

| Component | Supported Versions | Notes |
|---|---|---|
| **Python** | 3.11.x, 3.12.x | Tested with 3.11.9 |
| **Git** | >= 2.34.0 | Tested with 2.40.0.windows.1 |
| **OS** | Windows 10/11, Linux (Ubuntu 22.04+), macOS | Cross-platform path handling enforced |
| **Antigravity** | Native transport not implemented | Binary discovery is not a capability test; native and implicit fallback are refused. Select manual mode explicitly. |
| **JSON Schema** | Draft 2020-12 | Validated via `jsonschema` library |
| **YAML** | 1.2 (SafeLoader only) | PyYAML 6.0.3 |
