# Test Fixtures

## Valid netlists (must pass sanitizer with no violations)

| File | Purpose |
|------|---------|
| `valid_rc_filter.net` | RC low-pass filter with transient analysis and .MEAS |
| `valid_ac_analysis.net` | RC filter with AC sweep |
| `valid_op_analysis.net` | Voltage divider with .OP |
| `legitimate_system_comment.net` | Contains "system" and "shell" in comments, params, and component names -- must NOT trigger D-02 false positives |

## Attack fixtures (must be rejected with the correct ViolationType)

| File | ViolationType | Attack covered |
|------|--------------|---------------|
| `malicious_control_block.net` | CONTROL_BLOCK | ngspice .control block with shell exfiltration |
| `malicious_control_block_uppercase.net` | CONTROL_BLOCK | Uppercase .CONTROL to evade naive lowercase check |
| `malicious_lib_url_http.net` | LIB_URL | LTspice HTTP URL .lib (loads remote model) |
| `malicious_lib_url_https.net` | LIB_URL | HTTPS variant of the URL .lib attack |
| `malicious_unixcom.net` | UNIXCOM | set unixcom outside .control block |
| `malicious_path_traversal.net` | PATH_TRAVERSAL | .. in both .include and .lib paths |
| `malicious_codemodel.net` | CODEMODEL | XSPICE .codemodel (C shared library as arbitrary code) |
| `malicious_verilog_dll.net` | VERILOG_DLL | QSPICE .pragma (Verilog DLL loading) |
| `malicious_dll_reference.net` | VERILOG_DLL | Bare .dll reference in component line |

## Do not modify a fixture without understanding its attack

Each malicious fixture covers a specific threat vector documented in ARCHITECTURE.md
Section 3.2 and DECISIONS.md D-01 through D-05. If a fixture looks "too simple,"
that is intentional -- the simplest netlist that demonstrates the attack is the
most useful regression fixture.

## sample_models/

Stub .lib and .sub files used by model resolver tests. These are not real models.
The file content does not matter -- only the filenames and directory structure matter
for resolver tests.
