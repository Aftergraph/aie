from __future__ import annotations

import subprocess
from pathlib import Path


def _run(*args: str, cwd: Path) -> None:
    subprocess.run(args, cwd=cwd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def issue_test_pki(root: Path) -> dict[str, Path]:
    root.mkdir(parents=True, exist_ok=True)
    ca_key = root / "ca.key"
    ca_crt = root / "ca.crt"
    _run("openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", str(ca_key), "-out", str(ca_crt), "-days", "2", "-subj", "/CN=AIE Test CA", "-addext", "basicConstraints=critical,CA:TRUE", "-addext", "keyUsage=critical,keyCertSign,cRLSign", cwd=root)

    def issue(name: str, spiffe_id: str, *, client: bool, server: bool) -> tuple[Path, Path]:
        key = root / f"{name}.key"
        csr = root / f"{name}.csr"
        crt = root / f"{name}.crt"
        ext = root / f"{name}.ext"
        eku = []
        if client:
            eku.append("clientAuth")
        if server:
            eku.append("serverAuth")
        ext.write_text(
            "basicConstraints=critical,CA:FALSE\n"
            "keyUsage=critical,digitalSignature,keyEncipherment\n"
            f"extendedKeyUsage={','.join(eku)}\n"
            f"subjectAltName=URI:{spiffe_id}\n",
            encoding="utf-8",
        )
        _run("openssl", "req", "-new", "-newkey", "rsa:2048", "-nodes", "-keyout", str(key), "-out", str(csr), "-subj", f"/CN={name}", cwd=root)
        _run("openssl", "x509", "-req", "-in", str(csr), "-CA", str(ca_crt), "-CAkey", str(ca_key), "-CAcreateserial", "-out", str(crt), "-days", "2", "-sha256", "-extfile", str(ext), cwd=root)
        return crt, key

    agent_crt, agent_key = issue("agent", "spiffe://example.org/agent/refund", client=True, server=False)
    gw_a_crt, gw_a_key = issue("gw-a", "spiffe://example.org/gateway/a", client=True, server=True)
    gw_b_crt, gw_b_key = issue("gw-b", "spiffe://example.org/gateway/b", client=True, server=True)
    return {
        "ca": ca_crt,
        "agent_crt": agent_crt,
        "agent_key": agent_key,
        "gw_a_crt": gw_a_crt,
        "gw_a_key": gw_a_key,
        "gw_b_crt": gw_b_crt,
        "gw_b_key": gw_b_key,
    }
