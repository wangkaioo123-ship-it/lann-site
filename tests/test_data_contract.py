import csv
import tempfile
import unittest
from datetime import date
from pathlib import Path

from scripts.validate_data_contract import validate


def write_csv(path: Path, fields: list[str], rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


class DataContractTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.base = self.root / "base.csv"
        self.mapping = self.root / "mapping.csv"
        self.rent = self.root / "rent.csv"
        self.ops = self.root / "ops.csv"

    def tearDown(self):
        self.temp_dir.cleanup()

    def write_defaults(self, base_rows=None, mapping_rows=None, ops_rows=None):
        write_csv(
            self.base,
            ["点位ID", "门店名称", "门店状态", "record_id"],
            base_rows or [{"点位ID": "L0001", "门店名称": "上海花木店", "门店状态": "运营中", "record_id": "rec1"}],
        )
        write_csv(
            self.mapping,
            ["Hanson门店名称", "候选底表门店名称", "确认点位ID"],
            mapping_rows or [{"Hanson门店名称": "花木店", "候选底表门店名称": "上海花木店", "确认点位ID": "L0001"}],
        )
        write_csv(self.rent, ["点位ID"], [{"点位ID": "L0001"}])
        write_csv(
            self.ops,
            ["点位ID", "月份"],
            ops_rows or [{"点位ID": "L0001", "月份": "2026-06"}],
        )

    def issue_codes(self):
        return {issue.code for issue in validate(self.base, self.mapping, self.rent, self.ops, today=date(2026, 7, 18))}

    def test_clean_contract_has_no_errors(self):
        self.write_defaults()
        issues = validate(self.base, self.mapping, self.rent, self.ops, today=date(2026, 7, 18))
        self.assertFalse([issue for issue in issues if issue.severity == "ERROR"])

    def test_duplicate_site_id_blocks_join(self):
        self.write_defaults(
            base_rows=[
                {"点位ID": "L0001", "门店名称": "旧址店", "门店状态": "已终止", "record_id": "old"},
                {"点位ID": "L0001", "门店名称": "新址店", "门店状态": "运营中", "record_id": "new"},
            ]
        )
        self.assertIn("BASE_JOIN_KEY_NOT_UNIQUE", self.issue_codes())

    def test_confirmed_episodes_resolve_duplicate_join_key(self):
        self.write_defaults(
            base_rows=[
                {"点位ID": "L0001", "门店名称": "旧址店", "门店状态": "已终止", "record_id": "old"},
                {"点位ID": "L0001", "门店名称": "新址店", "门店状态": "运营中", "record_id": "new"},
            ]
        )
        episodes = self.root / "episodes.csv"
        write_csv(
            episodes,
            ["source_record_id", "analysis_point_id", "resolution_status", "hanson_store_name"],
            [
                {"source_record_id": "old", "analysis_point_id": "L0001-01", "resolution_status": "confirmed", "hanson_store_name": ""},
                {"source_record_id": "new", "analysis_point_id": "L0001-02", "resolution_status": "confirmed", "hanson_store_name": ""},
            ],
        )
        issues = validate(self.base, self.mapping, self.rent, self.ops, today=date(2026, 7, 18), episodes_path=episodes)
        self.assertNotIn("BASE_JOIN_KEY_NOT_UNIQUE", {issue.code for issue in issues})

    def test_changed_id_with_better_name_match_is_error(self):
        self.write_defaults(
            base_rows=[
                {"点位ID": "L0020", "门店名称": "上海宝杨宝龙店", "门店状态": "已终止", "record_id": "old"},
                {"点位ID": "L0087", "门店名称": "上海宝乐汇店", "门店状态": "运营中", "record_id": "new"},
            ],
            mapping_rows=[{"Hanson门店名称": "宝乐汇店", "候选底表门店名称": "上海宝乐汇店", "确认点位ID": "L0020"}],
            ops_rows=[{"点位ID": "L0020", "月份": "2026-06"}],
        )
        self.assertIn("MAPPING_BETTER_MATCH_CHANGED_ID", self.issue_codes())

    def test_stale_ops_is_warning(self):
        self.write_defaults(ops_rows=[{"点位ID": "L0001", "月份": "2026-03"}])
        self.assertIn("OPS_DATA_STALE", self.issue_codes())


if __name__ == "__main__":
    unittest.main()
