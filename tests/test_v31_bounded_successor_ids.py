from control_engine import kernel_v31 as core


def test_successor_ids_remain_bounded_across_many_repair_cycles():
    predecessor = core.deterministic_root_id("M1", "2026-08-31-r1", "G1")
    seen = set()

    for index in range(100):
        operation = "ASSURANCE" if index % 2 == 0 else "REPAIR"
        candidate_sha = f"{index + 1:040x}"
        successor = core._successor_id(predecessor, operation, candidate_sha)

        assert successor == core._successor_id(predecessor, operation, candidate_sha)
        assert successor.startswith(f"SUCCESSOR--{operation}--")
        assert len(successor) <= 90
        assert predecessor not in successor
        assert successor not in seen
        assert len(f"{successor}--run-00000000-0000-0000-0000-000000000000.json") < 255

        seen.add(successor)
        predecessor = successor


def test_successor_identity_rejects_invalid_operation_or_candidate_sha():
    predecessor = core.deterministic_root_id("M1", "2026-08-31-r1", "G1")

    for operation in ("IMPLEMENTATION", "PROJECT_INTEGRATION", ""):
        try:
            core._successor_id(predecessor, operation, "1" * 40)
        except core.KernelError:
            pass
        else:
            raise AssertionError("invalid successor operation accepted")

    for candidate_sha in (None, "", "not-a-sha"):
        try:
            core._successor_id(predecessor, "ASSURANCE", candidate_sha)
        except core.KernelError:
            pass
        else:
            raise AssertionError("invalid successor candidate SHA accepted")
