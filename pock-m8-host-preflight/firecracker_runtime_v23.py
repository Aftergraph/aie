from __future__ import annotations

import fcntl
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

from trust_v23 import canonical_json


SUPPORTED_ARCHES = {"x86_64", "aarch64"}
DENY_ALL_NETWORK = {"contract": "NetworkPolicy/v1", "mode": "deny-all", "allowHosts": []}
DENY_ALL_NETWORK_HASH = hashlib.sha256(canonical_json(DENY_ALL_NETWORK).encode("utf-8")).hexdigest()


def _sha_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _sha_obj(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _version_token(text: str | None) -> str | None:
    if not text:
        return None
    m = re.search(r"\bv?(\d+\.\d+\.\d+(?:[-+][A-Za-z0-9._-]+)?)\b", text)
    return m.group(1) if m else None


class MicroVMRuntimeImage:
    """Content-addressed Firecracker guest image identity.

    This is an image identity contract only. Inspecting kernel/rootfs bytes is not
    evidence that a microVM booted or that hardware isolation was exercised.
    """

    contract = "MicroVMRuntimeImage/v1"

    @classmethod
    def inspect(
        cls,
        kernel_path: str | Path,
        rootfs_path: str | Path,
        *,
        initrd_path: str | Path | None = None,
        rootfs_read_only: bool = False,
    ) -> dict[str, Any]:
        kernel = Path(kernel_path)
        rootfs = Path(rootfs_path)
        initrd = Path(initrd_path) if initrd_path else None
        for label, path in (("kernel", kernel), ("rootfs", rootfs)):
            if not path.exists() or not path.is_file():
                raise FileNotFoundError(f"microvm_{label}_missing:{path}")
            if path.stat().st_size <= 0:
                raise ValueError(f"microvm_{label}_empty")
        if initrd is not None:
            if not initrd.exists() or not initrd.is_file():
                raise FileNotFoundError(f"microvm_initrd_missing:{initrd}")
            if initrd.stat().st_size <= 0:
                raise ValueError("microvm_initrd_empty")

        immutable = {
            "contract": cls.contract,
            "architecture": platform.machine(),
            "kernel": {"sha256": _sha_file(kernel), "size": kernel.stat().st_size},
            "rootfs": {
                "sha256": _sha_file(rootfs),
                "size": rootfs.stat().st_size,
                "readOnly": bool(rootfs_read_only),
            },
            "initrd": None
            if initrd is None
            else {"sha256": _sha_file(initrd), "size": initrd.stat().st_size},
        }
        manifest_hash = _sha_obj(immutable)
        return {
            **immutable,
            "kernel": {**immutable["kernel"], "path": str(kernel.resolve())},
            "rootfs": {**immutable["rootfs"], "path": str(rootfs.resolve())},
            "initrd": None
            if initrd is None
            else {**immutable["initrd"], "path": str(initrd.resolve())},
            "manifestHash": manifest_hash,
            "digest": "sha256:" + manifest_hash,
            "truthStatus": "SOFTWARE_IMAGE_IDENTITY",
            "microvmBootProof": "UNVERIFIED",
        }


class FirecrackerHostAdmission:
    """Fail-closed host admission for a production Firecracker habitat.

    Ready means the host has the prerequisites to *attempt* an isolated boot.
    It is deliberately not equivalent to REAL_LOCAL_EXERCISED; that requires a
    successful guest boot and execution proof produced by a later boot gate.
    """

    contract = "FirecrackerHostAdmission/v1"

    def __init__(
        self,
        *,
        kvm_path: str = "/dev/kvm",
        firecracker_path: str | None = None,
        jailer_path: str | None = None,
        cgroup_root: str | Path = "/sys/fs/cgroup",
        required_version: str | None = None,
    ):
        self.kvm_path = str(kvm_path)
        self.firecracker_path = firecracker_path or shutil.which("firecracker")
        self.jailer_path = jailer_path or shutil.which("jailer")
        self.cgroup_root = Path(cgroup_root)
        self.required_version = required_version

    def _kvm(self) -> dict[str, Any]:
        p = Path(self.kvm_path)
        result = {
            "path": self.kvm_path,
            "exists": p.exists(),
            "readable": False,
            "writable": False,
            "usable": False,
            "apiVersion": None,
            "error": None,
        }
        if not p.exists():
            result["error"] = "kvm_missing"
            return result
        result["readable"] = os.access(p, os.R_OK)
        result["writable"] = os.access(p, os.W_OK)
        try:
            fd = os.open(p, os.O_RDWR | getattr(os, "O_CLOEXEC", 0))
        except OSError as exc:
            result["error"] = f"{type(exc).__name__}:{getattr(exc, 'errno', '')}"
            return result
        try:
            version = int(fcntl.ioctl(fd, 0xAE00, 0))  # KVM_GET_API_VERSION
            result["apiVersion"] = version
            result["usable"] = version > 0
            if version <= 0:
                result["error"] = "kvm_api_version_invalid"
        except OSError as exc:
            result["error"] = f"{type(exc).__name__}:{getattr(exc, 'errno', '')}"
        finally:
            os.close(fd)
        return result

    @staticmethod
    def _binary(path: str | None) -> dict[str, Any]:
        result = {"path": path, "exists": False, "executable": False, "versionText": None, "version": None, "error": None}
        if not path:
            result["error"] = "missing"
            return result
        p = Path(path)
        result["exists"] = p.exists()
        if not p.exists():
            result["error"] = "missing"
            return result
        result["executable"] = os.access(p, os.X_OK)
        if not result["executable"]:
            result["error"] = "not_executable"
            return result
        try:
            proc = subprocess.run([str(p), "--version"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=3, check=False)
            text = (proc.stdout or "").strip().splitlines()
            first = text[0][:240] if text else None
            result["versionText"] = first
            result["version"] = _version_token(first)
            if proc.returncode != 0:
                result["error"] = f"exit_{proc.returncode}"
        except Exception as exc:
            result["error"] = type(exc).__name__
        return result

    def status(self) -> dict[str, Any]:
        arch = platform.machine()
        kvm = self._kvm()
        firecracker = self._binary(self.firecracker_path)
        jailer = self._binary(self.jailer_path)
        cgroup_v2 = (self.cgroup_root / "cgroup.controllers").is_file()
        fc_version = firecracker.get("version")
        jailer_version = jailer.get("version")
        version_pair_known = bool(fc_version and jailer_version)
        version_match = bool(version_pair_known and fc_version == jailer_version)
        required_match = True if not self.required_version else (fc_version == self.required_version and jailer_version == self.required_version)

        blockers: list[str] = []
        if arch not in SUPPORTED_ARCHES:
            blockers.append("unsupported_architecture")
        if not kvm["usable"]:
            blockers.append("kvm_unavailable")
        if firecracker["error"] is not None or not firecracker["executable"]:
            blockers.append("firecracker_binary_unavailable")
        if jailer["error"] is not None or not jailer["executable"]:
            blockers.append("jailer_binary_unavailable")
        if not cgroup_v2:
            blockers.append("cgroup_v2_unavailable")
        if firecracker["executable"] and jailer["executable"] and not version_match:
            blockers.append("firecracker_jailer_version_mismatch_or_unknown")
        if self.required_version and firecracker["executable"] and jailer["executable"] and not required_match:
            blockers.append("required_firecracker_version_mismatch")

        ready = len(blockers) == 0
        material = {
            "contract": self.contract,
            "architecture": arch,
            "kernelRelease": platform.release(),
            "kvmApiVersion": kvm["apiVersion"],
            "firecrackerVersion": fc_version,
            "jailerVersion": jailer_version,
            "cgroupV2": cgroup_v2,
            "requiredVersion": self.required_version,
        }
        return {
            **material,
            "hostIdentityHash": _sha_obj(material),
            "kvm": kvm,
            "firecracker": firecracker,
            "jailer": jailer,
            "versionPairKnown": version_pair_known,
            "versionMatch": version_match,
            "requiredVersionMatch": required_match,
            "productionJailerRequired": True,
            "defaultSeccompRequired": True,
            "cgroupV2": cgroup_v2,
            "readyToAttemptBoot": ready,
            "blockers": blockers,
            "truthStatus": "READY_UNEXERCISED" if ready else "BLOCKED",
            "microvmBootProof": "UNVERIFIED" if ready else "BLOCKED",
            "hardwareAttestation": "BLOCKED",
        }

    def require_ready(self) -> dict[str, Any]:
        status = self.status()
        if not status["readyToAttemptBoot"]:
            raise RuntimeError("firecracker_host_admission_blocked:" + ",".join(status["blockers"]))
        return status


class FirecrackerLaunchPlanner:
    """Deterministic, non-executing launch plan for the first M8 boot gate."""

    contract = "FirecrackerLaunchPlan/v1"

    @classmethod
    def plan(
        cls,
        image: dict[str, Any],
        *,
        network_policy: dict[str, Any] | None = None,
        vcpu_count: int = 1,
        mem_size_mib: int = 256,
        boot_args: str = "console=ttyS0 reboot=k panic=1 pci=off",
        vsock_enabled: bool = False,
        guest_cid: int = 3,
        vsock_uds_path: str = "/agent.vsock",
    ) -> dict[str, Any]:
        if image.get("contract") != MicroVMRuntimeImage.contract:
            raise ValueError("firecracker_image_contract_invalid")
        if not str(image.get("digest") or "").startswith("sha256:"):
            raise ValueError("firecracker_image_digest_invalid")
        policy = network_policy or DENY_ALL_NETWORK
        if policy != DENY_ALL_NETWORK:
            raise PermissionError("firecracker_scoped_allowlist_not_implemented")
        vcpu_count = int(vcpu_count)
        mem_size_mib = int(mem_size_mib)
        if not (1 <= vcpu_count <= 32):
            raise ValueError("firecracker_vcpu_count_invalid")
        if not (128 <= mem_size_mib <= 65536):
            raise ValueError("firecracker_memory_invalid")
        vsock_enabled = bool(vsock_enabled)
        guest_cid = int(guest_cid)
        if vsock_enabled:
            if not (3 <= guest_cid <= 2**32 - 1):
                raise ValueError("firecracker_vsock_guest_cid_invalid")
            if not vsock_uds_path.startswith("/") or ".." in Path(vsock_uds_path).parts or vsock_uds_path in {"/", ""}:
                raise ValueError("firecracker_vsock_uds_path_invalid")

        config = {
            "machine-config": {"vcpu_count": vcpu_count, "mem_size_mib": mem_size_mib},
            "boot-source": {
                "kernel_image_path": image["kernel"]["path"],
                "boot_args": boot_args,
                **({"initrd_path": image["initrd"]["path"]} if image.get("initrd") else {}),
            },
            "drives": [
                {
                    "drive_id": "rootfs",
                    "path_on_host": image["rootfs"]["path"],
                    "is_root_device": True,
                    "is_read_only": bool(image["rootfs"].get("readOnly")),
                }
            ],
            # No NIC is attached for M8 phase A deny-all. A scoped network policy
            # remains a separate capability gate and must not be simulated here.
            "network-interfaces": [],
            **({"vsock": {"guest_cid": guest_cid, "uds_path": vsock_uds_path}} if vsock_enabled else {}),
            "action": {"action_type": "InstanceStart"},
        }
        identity = {
            "contract": cls.contract,
            "imageDigest": image["digest"],
            "kernelSha256": image["kernel"]["sha256"],
            "rootfsSha256": image["rootfs"]["sha256"],
            "initrdSha256": image["initrd"]["sha256"] if image.get("initrd") else None,
            "networkPolicyHash": DENY_ALL_NETWORK_HASH,
            "vcpuCount": vcpu_count,
            "memSizeMiB": mem_size_mib,
            "bootArgs": boot_args,
            "jailerRequired": True,
            "defaultSeccompRequired": True,
            "networkMode": "no-interface-deny-all",
            "vsockEnabled": vsock_enabled,
            "guestCid": guest_cid if vsock_enabled else None,
            "vsockUdsPath": vsock_uds_path if vsock_enabled else None,
        }
        plan_hash = _sha_obj(identity)
        return {
            **identity,
            "planHash": plan_hash,
            "firecrackerConfig": config,
            "truthStatus": "SOFTWARE_LAUNCH_PLAN",
            "microvmBootProof": "UNVERIFIED",
            "scopedAllowlistKernelEnforcement": "BLOCKED",
        }


class HabitatFirecrackerBackend:
    """M8 phase-A backend boundary.

    This class deliberately stops at truthful host/image/launch admission on a
    host where KVM cannot be exercised. The future boot gate must add a genuine
    guest boot receipt before truthStatus may become REAL_LOCAL_EXERCISED.
    """

    contract = "HabitatFirecrackerBackend/v1"
    proof_contract = "HabitatMicroVMExecutionProof/v1"

    def __init__(self, *, host: FirecrackerHostAdmission | None = None):
        self.host = host or FirecrackerHostAdmission(
            kvm_path=os.environ.get("POCK_KVM_PATH", "/dev/kvm"),
            firecracker_path=os.environ.get("POCK_FIRECRACKER_BIN") or None,
            jailer_path=os.environ.get("POCK_FIRECRACKER_JAILER_BIN") or None,
            cgroup_root=os.environ.get("POCK_CGROUP_ROOT", "/sys/fs/cgroup"),
            required_version=os.environ.get("POCK_FIRECRACKER_REQUIRED_VERSION") or None,
        )

    def status(self) -> dict[str, Any]:
        host = self.host.status()
        return {
            "contract": self.contract,
            "proofContract": self.proof_contract,
            "bootDriverContract": "FirecrackerBootDriver/v1",
            "bootObservationContract": "FirecrackerBootObservation/v1",
            "bootProofContract": "HabitatMicroVMBootProof/v1",
            "executionProofContract": self.proof_contract,
            "hostAdmission": host,
            "imageContract": MicroVMRuntimeImage.contract,
            "launchPlanContract": FirecrackerLaunchPlanner.contract,
            "bootDriverImplementation": "AVAILABLE_UNEXERCISED_ON_REAL_KVM",
            "denyAllNetworkPlan": "READY",
            "kernelEgressPolicyContract": "KernelEgressPolicy/v1",
            "kernelEgressEnforcerContract": "KernelEgressEnforcer/v1",
            "scopedAllowlistSoftware": "IMPLEMENTED_UNEXERCISED_KERNEL",
            "scopedAllowlistKernelEnforcement": "BLOCKED",
            "guestBoot": "UNVERIFIED" if host["readyToAttemptBoot"] else "BLOCKED",
            "executionAllowed": False,
            "hardwareAttestation": "BLOCKED",
            "truthStatus": "READY_FOR_BOOT_EXERCISE" if host["readyToAttemptBoot"] else "BLOCKED_HOST_SUBSTRATE",
            "nonClaims": [
                "microvm boot exercised",
                "scoped kernel allowlist enforcement",
                "hardware attestation",
                "production deployment",
            ],
        }

    def plan(self, kernel_path: str | Path, rootfs_path: str | Path, **kwargs: Any) -> dict[str, Any]:
        image = MicroVMRuntimeImage.inspect(kernel_path, rootfs_path, initrd_path=kwargs.pop("initrd_path", None))
        launch = FirecrackerLaunchPlanner.plan(image, **kwargs)
        return {"contract": self.contract, "hostAdmission": self.host.status(), "runtimeImage": image, "launchPlan": launch}

    def execute(self, *_args: Any, **_kwargs: Any) -> dict[str, Any]:
        self.host.require_ready()
        # A real host may only cross this boundary once the jailer+API boot driver
        # is exercised and emits HabitatMicroVMExecutionProof/v1. Do not silently
        # fall back to namespaces or subprocesses.
        raise RuntimeError("firecracker_boot_driver_not_yet_exercised")
