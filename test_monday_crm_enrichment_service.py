import unittest

import monday_crm_enrichment_service as svc


class MondayCRMEnrichmentTests(unittest.TestCase):
    def test_enrichment_includes_sources_and_citations(self) -> None:
        result = svc.enrich_lead(
            {
                "lead": {
                    "id": "ld_1001",
                    "email": "vp.sales@acme.com",
                    "company": "Acme",
                    "title": "VP Sales",
                    "website": "https://acme.com",
                },
                "lookup_sources": [
                    {
                        "kind": "linkedin",
                        "title": "Acme LinkedIn",
                        "url": "https://linkedin.com/company/acme",
                        "note": "Validated company profile",
                    }
                ],
            }
        )

        self.assertEqual(result["lead_id"], "ld_1001")
        self.assertIn("source_references", result)
        self.assertGreaterEqual(len(result["source_references"]), 3)
        self.assertEqual(
            result["enriched_fields"]["company_website"]["source_refs"],
            ["src_website"],
        )
        self.assertEqual(
            result["enriched_fields"]["external_source_count"]["source_refs"],
            ["src_lookup_1"],
        )
        self.assertEqual(result["enriched_fields"]["contact_seniority"]["value"], "executive")

    def test_requested_fields_filter(self) -> None:
        result = svc.enrich_lead(
            {
                "lead": {
                    "id": "ld_2002",
                    "email": "buyer@gmail.com",
                    "title": "Manager",
                },
                "requested_fields": ["company_domain", "fit_tier"],
            }
        )

        self.assertEqual(set(result["enriched_fields"].keys()), {"company_domain", "fit_tier"})
        self.assertEqual(result["enriched_fields"]["fit_tier"]["value"], "low")

    def test_invalid_input_raises(self) -> None:
        with self.assertRaises(ValueError):
            svc.enrich_lead({"lead": "not-an-object"})

    def test_configured_board_ids(self) -> None:
        prev = svc.MONDAY_BOARD_IDS
        try:
            svc.MONDAY_BOARD_IDS = "18397429943, 777, bad,"
            self.assertEqual(svc.configured_board_ids(), [18397429943, 777])
        finally:
            svc.MONDAY_BOARD_IDS = prev

    def test_board_query_builder(self) -> None:
        query = svc._build_board_summary_query([18397429943, 777])
        self.assertIn("boards(ids: [18397429943,777])", query)


if __name__ == "__main__":
    unittest.main()
