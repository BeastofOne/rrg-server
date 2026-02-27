def is_same_property(name1, name2):
    """Check if two property names refer to the same property.
    Handles Crexi naming: 'Name' vs 'Name in City'.
    """
    a = name1.lower().strip()
    b = name2.lower().strip()
    if a == b:
        return True
    shorter, longer = (a, b) if len(a) <= len(b) else (b, a)
    if longer.startswith(shorter):
        remainder = longer[len(shorter):]
        if remainder.startswith(" in "):
            return True
    return False

def main(leads: list):
    groups = {}
    for lead in leads:
        email = lead.get("email", "").strip().lower()
        if not email:
            continue
        if email not in groups:
            groups[email] = {"name": lead["name"], "email": email, "phone": lead.get("phone", ""), "source": lead.get("source", ""), "source_type": lead.get("source_type", ""), "is_new": lead.get("is_new", True), "has_nda": lead.get("has_nda", False), "is_followup": lead.get("is_followup", False), "wiseagent_client_id": lead.get("wiseagent_client_id"), "lead_type": lead.get("lead_type", ""), "city": lead.get("city", ""), "properties": [], "notification_message_ids": []}
        # Deduplicate properties by property_name — different actions on the same
        # property (OM + CA + flyer) should not count as multiple properties.
        # Also handles Crexi name variants: "Name" vs "Name in City".
        prop_name = lead.get("property_name", "").strip().lower()
        existing_props = groups[email]["properties"]
        match_idx = None
        for i, p in enumerate(existing_props):
            if is_same_property(prop_name, p.get("property_name", "")):
                match_idx = i
                break
        new_prop = {"property_name": lead.get("property_name", ""), "canonical_name": lead.get("canonical_name", ""), "property_address": lead.get("property_address", ""), "deal_id": lead.get("deal_id", ""), "brochure_highlights": lead.get("brochure_highlights", ""), "asking_price": lead.get("asking_price", ""), "is_mapped": lead.get("is_mapped"), "lead_magnet": lead.get("lead_magnet", False), "response_override": lead.get("response_override", "")}
        if match_idx is None or not prop_name:
            existing_props.append(new_prop)
        elif len(prop_name) > len(existing_props[match_idx].get("property_name", "").strip().lower()):
            # Replace with the longer/more detailed name (has city suffix)
            existing_props[match_idx] = new_prop
        msg_id = lead.get("notification_message_id", "")
        if msg_id:
            groups[email]["notification_message_ids"].append(msg_id)
    standard_leads = list(groups.values())
    multi_property_count = sum(1 for g in standard_leads if len(g["properties"]) > 1)
    return {"standard_leads": standard_leads, "info_requests": [], "total": len(standard_leads), "info_request_count": 0, "multi_property_count": multi_property_count}
