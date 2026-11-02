from __future__ import annotations

from cosmic_resolve.tools import get_case


def main() -> None:
    case = get_case("C-1001")
    print(f"Loaded case: {case.case_id} ({case.case_type})")
    print("Repository is running in deterministic starter mode.")


if __name__ == "__main__":
    main()
