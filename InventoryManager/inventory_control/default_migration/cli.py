"""Redacted CLI boundary for default-tenant migration orchestration.

The module never imports an application database configuration or discovers a
DSN.  Planning/journal commands remain offline.  Apply commands can run only
through an explicitly injected phase registry whose adapters own their already
validated database connections; no provider/print adapter is inferred here.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from datetime import datetime, timezone
from typing import Callable, Mapping, Sequence, TextIO

from inventory_control.crypto import RootKeyLoadError, load_root_key

from .identity_inputs import DefaultTenantIdentityInputError
from .manifest import (
    MigrationExecutionMode,
    MigrationManifestError,
    MigrationPhase,
    build_execution_plan,
    plan_legacy_rollback,
)
from .persistence import MigrationJournalFileStore
from .command import DefaultMigrationCommand
from .runner import DefaultMigrationPhaseExecutor, DefaultMigrationRunner
from .serde import (
    manifest_from_document,
    manifest_from_identity_template_document,
    manifest_from_source_baseline_identity_template_document,
    manifest_to_document,
)
from .source_baseline import (
    DefaultSourceBaselineError,
    source_baseline_evidence_from_document,
)
from .historical_boundary import (
    DefaultHistoricalBoundaryError,
    source_migration_preflight_from_document,
)
from .bundle import (
    MigrationBundleError,
    build_default_migration_bundle_evidence,
    migration_bundle_evidence_from_document,
    migration_bundle_evidence_to_document,
)


_MAX_DOCUMENT_BYTES = 1_048_576


def main(
    argv: Sequence[str] | None = None,
    *,
    stdout: TextIO = sys.stdout,
    stderr: TextIO = sys.stderr,
    phase_executors: Mapping[
        MigrationPhase, DefaultMigrationPhaseExecutor
    ] | None = None,
    clock: Callable[[], datetime] | None = None,
) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "create-migration-bundle-evidence":
            migration_bundle = build_default_migration_bundle_evidence(
                args.repository_root
            )
            _emit(
                stdout,
                {
                    "ok": True,
                    "migration_bundle": (
                        migration_bundle_evidence_to_document(
                            migration_bundle
                        )
                    ),
                    "summary": dict(migration_bundle.safe_summary()),
                },
            )
            return 0
        if args.command == "validate-migration-bundle":
            manifest = manifest_from_document(_load_json(args.manifest))
            documented = migration_bundle_evidence_from_document(
                _load_json(args.migration_bundle_evidence)
            )
            current = build_default_migration_bundle_evidence(
                args.repository_root
            )
            if current != documented:
                raise MigrationBundleError()
            current.require_manifest(manifest)
            _emit(
                stdout,
                {"ok": True, "migration_bundle": dict(current.safe_summary())},
            )
            return 0
        if args.command in {
            "create-manifest",
            "create-manifest-from-source-baseline",
            "create-manifest-from-source-preflight",
        }:
            root_key = load_root_key(
                args.root_key_file,
                version=args.root_key_version,
                expected_fingerprint_sha256=args.root_key_fingerprint,
            )
            display_name = _load_controlled_text(args.display_name_file)
            first_admin_phone = _load_controlled_text(
                args.first_admin_phone_file
            )
            source_preflight = (
                source_migration_preflight_from_document(
                    _load_json(args.source_preflight)
                )
                if args.command == "create-manifest-from-source-preflight"
                else None
            )
            source_baseline = (
                source_preflight.source_baseline
                if source_preflight is not None
                else (
                    source_baseline_evidence_from_document(
                        _load_json(args.source_baseline)
                    )
                    if args.command == "create-manifest-from-source-baseline"
                    else None
                )
            )
            migration_bundle = (
                migration_bundle_evidence_from_document(
                    _load_json(args.migration_bundle_evidence)
                )
                if source_baseline is not None
                else None
            )
            if source_baseline is None:
                manifest, inputs = manifest_from_identity_template_document(
                    _load_json(args.template),
                    root_key=root_key,
                    display_name=display_name,
                    first_admin_phone=first_admin_phone,
                )
            else:
                manifest, inputs = (
                    manifest_from_source_baseline_identity_template_document(
                        _load_json(args.template),
                        source_baseline=source_baseline,
                        migration_bundle=migration_bundle,
                        root_key=root_key,
                        display_name=display_name,
                        first_admin_phone=first_admin_phone,
                    )
                )
            output = {
                "ok": True,
                "manifest": manifest_to_document(manifest),
                "identity_inputs": dict(inputs.redacted_summary()),
            }
            if source_baseline is not None:
                output["source_baseline"] = dict(
                    source_baseline.redacted_summary()
                )
                output["migration_bundle"] = dict(
                    migration_bundle.safe_summary()
                )
            if source_preflight is not None:
                output["source_preflight"] = dict(
                    source_preflight.redacted_summary()
                )
            _emit(
                stdout,
                output,
            )
            return 0
        manifest = manifest_from_document(_load_json(args.manifest))
        if args.command == "validate-manifest":
            _emit(
                stdout,
                {
                    "ok": True,
                    "manifest": dict(manifest.redacted_summary()),
                },
            )
            return 0
        if args.command == "initialize-journal":
            journal = MigrationJournalFileStore(args.journal).initialize(manifest)
            _emit(
                stdout,
                {
                    "ok": True,
                    "manifest_digest": journal.manifest_digest.hex(),
                    "completed_phases": [
                        item.phase.value for item in journal.completed
                    ],
                    "next_phase": (
                        None
                        if journal.next_phase is None
                        else journal.next_phase.value
                    ),
                    "tenant_aware_writes_authoritative": (
                        journal.tenant_aware_writes_enabled_at is not None
                    ),
                },
            )
            return 0
        journal = MigrationJournalFileStore(args.journal).load()
        if args.command in {
            "run-to-authoritative-boundary",
            "run-contract",
        }:
            command = DefaultMigrationCommand(
                MigrationJournalFileStore(args.journal),
                executors=phase_executors or {},
                clock=clock,
            )
            result = (
                command.run_to_authoritative_boundary(manifest)
                if args.command == "run-to-authoritative-boundary"
                else command.run_contract(manifest)
            )
            output = dict(result.redacted_summary())
            output["ok"] = True
            _emit(stdout, output)
            return 0
        if args.command == "mark-tenant-aware-writes-authoritative":
            updated = DefaultMigrationRunner(
                MigrationJournalFileStore(args.journal)
            ).mark_tenant_aware_writes_authoritative(
                manifest,
                enabled_at=_parse_utc(args.enabled_at),
            )
            _emit(
                stdout,
                {
                    "ok": True,
                    "manifest_digest": updated.manifest_digest.hex(),
                    "tenant_aware_writes_authoritative": True,
                    "enabled_at": (
                        updated.tenant_aware_writes_enabled_at.isoformat()
                    ),
                    "legacy_rollback_allowed": False,
                },
            )
            return 0
        if args.command == "run-phase":
            phase = MigrationPhase(args.phase)
            mode = MigrationExecutionMode(args.mode)
            executor = (
                None
                if phase_executors is None
                else phase_executors.get(phase)
            )
            result = DefaultMigrationRunner(
                MigrationJournalFileStore(args.journal),
                clock=clock,
            ).run_phase(
                manifest,
                phase=phase,
                mode=mode,
                executor=executor,
            )
            output = dict(result.redacted_summary())
            output["ok"] = True
            if result.plan is not None:
                output.update(
                    {
                        "prerequisites": list(result.plan.prerequisites),
                        "completion_conditions": list(
                            result.plan.completion_conditions
                        ),
                        "stop_conditions": list(result.plan.stop_conditions),
                        "rollback_action": result.plan.rollback_action,
                    }
                )
            if result.evidence is not None:
                output["completion_evidence"] = {
                    "completed_at": result.evidence.completed_at.isoformat(),
                    "executor_reference": result.evidence.executor_reference,
                    "input_state_digest": (
                        result.evidence.input_state_digest.hex()
                    ),
                    "result_state_digest": (
                        result.evidence.result_state_digest.hex()
                    ),
                }
            _emit(stdout, output)
            return 0
        if args.command == "plan":
            requested = (
                None
                if args.phase is None
                else MigrationPhase(args.phase)
            )
            plan = build_execution_plan(
                manifest,
                journal,
                mode=MigrationExecutionMode(args.mode),
                requested_phase=requested,
            )
            _emit(
                stdout,
                {
                    "ok": True,
                    "manifest_digest": plan.manifest_digest.hex(),
                    "phase": plan.phase.value,
                    "mode": plan.mode.value,
                    "mutations_allowed": plan.mutations_allowed,
                    "provider_or_print_side_effects_allowed": (
                        plan.provider_or_print_side_effects_allowed
                    ),
                    "prerequisites": list(plan.prerequisites),
                    "completion_conditions": list(plan.completion_conditions),
                    "stop_conditions": list(plan.stop_conditions),
                    "rollback_action": plan.rollback_action,
                },
            )
            return 0
        rollback = plan_legacy_rollback(manifest, journal)
        _emit(
            stdout,
            {
                "ok": True,
                "manifest_digest": rollback.manifest_digest.hex(),
                "actions": list(rollback.actions),
                "preserves_expand_and_audit_facts": (
                    rollback.preserves_expand_and_audit_facts
                ),
                "reverses_business_data": rollback.reverses_business_data,
            },
        )
        return 0
    except (
        DefaultTenantIdentityInputError,
        DefaultHistoricalBoundaryError,
        DefaultSourceBaselineError,
        MigrationBundleError,
        MigrationManifestError,
        OSError,
        RootKeyLoadError,
        UnicodeError,
        ValueError,
        json.JSONDecodeError,
    ):
        _emit(
            stderr,
            {
                "ok": False,
                "error": (
                    "MIGRATION_EXECUTION_REJECTED"
                    if _is_execution_command(args.command)
                    else "MIGRATION_DOCUMENT_REJECTED"
                ),
            },
        )
        return 2
    except Exception:
        if not _is_execution_command(args.command):
            raise
        _emit(
            stderr,
            {"ok": False, "error": "MIGRATION_EXECUTION_REJECTED"},
        )
        return 2


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="default-tenant-migration-plan")
    subparsers = parser.add_subparsers(dest="command", required=True)
    create_bundle = subparsers.add_parser(
        "create-migration-bundle-evidence"
    )
    create_bundle.add_argument(
        "--repository-root",
        type=Path,
        required=True,
    )
    create = subparsers.add_parser("create-manifest")
    _add_create_manifest_arguments(create)
    create_from_source = subparsers.add_parser(
        "create-manifest-from-source-baseline"
    )
    _add_create_manifest_arguments(create_from_source)
    create_from_source.add_argument(
        "--source-baseline",
        type=Path,
        required=True,
    )
    create_from_source.add_argument(
        "--migration-bundle-evidence",
        type=Path,
        required=True,
    )
    create_from_preflight = subparsers.add_parser(
        "create-manifest-from-source-preflight"
    )
    _add_create_manifest_arguments(create_from_preflight)
    create_from_preflight.add_argument(
        "--source-preflight",
        type=Path,
        required=True,
    )
    create_from_preflight.add_argument(
        "--migration-bundle-evidence",
        type=Path,
        required=True,
    )

    validate = subparsers.add_parser("validate-manifest")
    validate.add_argument("--manifest", type=Path, required=True)

    validate_bundle = subparsers.add_parser("validate-migration-bundle")
    validate_bundle.add_argument("--manifest", type=Path, required=True)
    validate_bundle.add_argument(
        "--migration-bundle-evidence",
        type=Path,
        required=True,
    )
    validate_bundle.add_argument(
        "--repository-root",
        type=Path,
        required=True,
    )

    initialize = subparsers.add_parser("initialize-journal")
    initialize.add_argument("--manifest", type=Path, required=True)
    initialize.add_argument("--journal", type=Path, required=True)

    plan = subparsers.add_parser("plan")
    plan.add_argument("--manifest", type=Path, required=True)
    plan.add_argument("--journal", type=Path, required=True)
    plan.add_argument(
        "--mode",
        choices=[item.value for item in MigrationExecutionMode],
        required=True,
    )
    plan.add_argument(
        "--phase",
        choices=[item.value for item in MigrationPhase],
    )

    run = subparsers.add_parser("run-phase")
    run.add_argument("--manifest", type=Path, required=True)
    run.add_argument("--journal", type=Path, required=True)
    run.add_argument(
        "--mode",
        choices=[item.value for item in MigrationExecutionMode],
        required=True,
    )

    run_boundary = subparsers.add_parser(
        "run-to-authoritative-boundary"
    )
    run_boundary.add_argument("--manifest", type=Path, required=True)
    run_boundary.add_argument("--journal", type=Path, required=True)

    run_contract = subparsers.add_parser("run-contract")
    run_contract.add_argument("--manifest", type=Path, required=True)
    run_contract.add_argument("--journal", type=Path, required=True)
    run.add_argument(
        "--phase",
        choices=[item.value for item in MigrationPhase],
        required=True,
    )

    rollback = subparsers.add_parser("rollback-before-authoritative-write")
    rollback.add_argument("--manifest", type=Path, required=True)
    rollback.add_argument("--journal", type=Path, required=True)

    authoritative = subparsers.add_parser(
        "mark-tenant-aware-writes-authoritative"
    )
    authoritative.add_argument("--manifest", type=Path, required=True)
    authoritative.add_argument("--journal", type=Path, required=True)
    authoritative.add_argument("--enabled-at", required=True)
    return parser


def _add_create_manifest_arguments(
    parser: argparse.ArgumentParser,
) -> None:
    parser.add_argument("--template", type=Path, required=True)
    parser.add_argument("--root-key-file", type=Path, required=True)
    parser.add_argument("--root-key-version", type=int, required=True)
    parser.add_argument("--root-key-fingerprint")
    parser.add_argument("--display-name-file", type=Path, required=True)
    parser.add_argument("--first-admin-phone-file", type=Path, required=True)


def _is_execution_command(value: object) -> bool:
    return value in {
        "run-phase",
        "run-to-authoritative-boundary",
        "mark-tenant-aware-writes-authoritative",
        "run-contract",
        "rollback-before-authoritative-write",
    }


def _load_json(path: Path) -> object:
    raw = path.read_bytes()
    if len(raw) > _MAX_DOCUMENT_BYTES:
        raise OSError("document is too large")
    return json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object)


def _load_controlled_text(path: Path) -> str:
    raw = path.read_bytes()
    if not raw or len(raw) > 1_024 or b"\x00" in raw or b"\r" in raw:
        raise OSError("controlled input is invalid")
    if raw.endswith(b"\n"):
        raw = raw[:-1]
    if not raw or b"\n" in raw:
        raise OSError("controlled input is invalid")
    return raw.decode("utf-8")


def _parse_utc(value: object) -> datetime:
    if not isinstance(value, str) or not value or value.endswith("z"):
        raise ValueError("authoritative-write time is invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise ValueError("authoritative-write time is invalid") from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("authoritative-write time is invalid")
    normalized = parsed.astimezone(timezone.utc)
    if parsed.utcoffset().total_seconds() != 0:
        raise ValueError("authoritative-write time must be UTC")
    return normalized


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise json.JSONDecodeError("duplicate object key", key, 0)
        value[key] = item
    return value


def _emit(stream: TextIO, value: object) -> None:
    stream.write(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        )
        + "\n"
    )


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
