import wmill
import json

def main(leads: list):
    mapping_raw = wmill.get_variable("f/switchboard/property_mapping")
    mapping = json.loads(mapping_raw) if isinstance(mapping_raw, str) else mapping_raw
    properties = mapping.get("mappings", [])
    alias_map = {}
    for prop in properties:
        for alias in prop.get("aliases", []):
            alias_map[alias.lower()] = prop
    enriched = []
    for lead in leads:
        result = dict(lead)
        prop_name = lead.get("property_name", "").strip()
        source_type = lead.get("source_type", "")
        if source_type in ("crexi_om", "crexi_flyer", "loopnet", "bizbuysell"):
            matched = alias_map.get(prop_name.lower())
            if matched:
                result["is_mapped"] = True
                result["canonical_name"] = matched["canonical_name"]
                result["deal_id"] = matched.get("hubspot_deal_id", "")
                result["brochure_highlights"] = matched.get("brochure_highlights", "")
                result["lead_magnet"] = matched.get("lead_magnet", False)
                result["response_override"] = matched.get("response_override", "")
                result["property_address"] = matched.get("property_address", "")
                result["asking_price"] = matched.get("asking_price", "")
            else:
                result["is_mapped"] = False
                result["canonical_name"] = prop_name
                result["deal_id"] = ""
                result["brochure_highlights"] = ""
                result["lead_magnet"] = False
                result["response_override"] = ""
                result["property_address"] = ""
                result["asking_price"] = ""
        else:
            result["is_mapped"] = None
            result["canonical_name"] = prop_name
            result["deal_id"] = ""
            result["brochure_highlights"] = ""
            result["lead_magnet"] = False
            result["response_override"] = ""
            result["property_address"] = lead.get("property_address", "")
        enriched.append(result)
    return enriched
