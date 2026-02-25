# Module D: Generate Drafts with Gmail Draft Creation
# Uses Gmail API directly via OAuth to create drafts in teamgotcher@gmail.com
#
# Commercial templates (Crexi/LoopNet) and Lead Magnet signed by Larry.
# Residential templates (Realtor.com, Seller Hub, Social Connect) signed by Andrea.
# Followup detection comes from Module A (WiseAgent notes), not Gmail sent folder.

#extra_requirements:
#google-api-python-client
#google-auth

import wmill
import json
import base64
from email.mime.text import MIMEText
from datetime import datetime, timezone
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials


# ~500 common US first names (SSA data) for validating lead names vs company names
COMMON_FIRST_NAMES = {
    "aaron","abby","abigail","adam","addison","adrian","aiden","al","alan","albert",
    "alec","alex","alexander","alexandra","alexis","alice","alicia","alison","allison",
    "alyssa","amanda","amber","amy","ana","andrea","andrew","angela","angelina","angie",
    "ann","anna","anne","annette","anthony","antonio","april","archie","aria","ariana",
    "arthur","ashley","aubrey","audrey","austin","autumn","ava","avery","bailey","barbara",
    "barry","beatrice","becky","bella","ben","benjamin","bernard","bernice","beth","bethany",
    "betty","beverly","bill","billy","blake","bob","bobby","bonnie","brad","bradley",
    "brandi","brandon","brenda","brent","brett","brian","bridget","brittany","brooke",
    "brooklyn","bruce","bryan","bryce","caitlin","caitlyn","caleb","cameron","camille",
    "carl","carla","carlos","carmen","carol","caroline","carolyn","carrie","carter","casey",
    "catherine","cathy","chad","charlene","charles","charlie","charlotte","chase","chelsea",
    "cheryl","chris","christian","christina","christine","christopher","christy","cindy",
    "claire","clara","clarence","clark","claude","claudia","clay","clayton","cliff","clifford",
    "clint","clinton","cody","colby","cole","colin","colleen","colton","conner","connor",
    "connie","cooper","corey","courtney","craig","crystal","curt","curtis","cynthia",
    "daisy","dakota","dale","dallas","dalton","dan","dana","daniel","danielle","danny",
    "daphne","darla","darlene","darrell","darren","daryl","dave","david","dawn","dean",
    "deanna","debbie","deborah","debra","dee","delores","denise","dennis","derek","derrick",
    "destiny","devin","devon","diana","diane","dianne","dolores","dominic","don","donald",
    "donna","doris","dorothy","doug","douglas","drew","duane","dustin","dwight","dylan",
    "earl","ed","eddie","edgar","edith","edna","edward","edwin","eileen","elaine","elena",
    "eli","elijah","elizabeth","ella","ellen","ellie","emily","emma","eric","erica","erik",
    "erin","ernest","ethan","eugene","eva","evan","evelyn","faith","faye","felicia","florence",
    "frances","francis","frank","franklin","fred","frederick","gabe","gabriel","gabriella",
    "gabrielle","gail","garrett","gary","gavin","gene","george","gerald","geraldine","gina",
    "gladys","glen","glenn","gloria","gordon","grace","grant","greg","gregory","gretchen",
    "gwen","gwendolyn","hailey","haley","hannah","harold","harper","harriet","harry","harvey",
    "hayden","hazel","heather","hector","heidi","helen","henry","herbert","holly","hope",
    "howard","hudson","hugh","hunter","ian","ida","irene","iris","irma","isaac","isabel",
    "isabella","ivan","ivy","jack","jackie","jackson","jacob","jacqueline","jade","jaime",
    "jake","james","jamie","jan","jane","janet","janice","jared","jasmine","jason","jay",
    "jayden","jean","jeanette","jeanne","jeff","jeffery","jeffrey","jen","jenna","jennifer",
    "jenny","jeremy","jerome","jerry","jesse","jessica","jessie","jill","jim","jimmy",
    "jo","joan","joann","joanne","jocelyn","jodi","jody","joe","joel","joey","john","johnny",
    "jon","jonathan","jordan","jorge","jose","joseph","josh","joshua","joy","joyce","juan",
    "juanita","judith","judy","julia","julian","julie","june","justin","kaitlin","kaitlyn",
    "kara","karen","kari","karl","kate","katelyn","katherine","kathleen","kathryn","kathy",
    "katie","katrina","kay","kayla","kaylee","keith","kelley","kelly","kelsey","ken",
    "kendra","kenneth","kenny","kent","keri","kerri","kerry","kevin","kim","kimberly",
    "kirk","krista","kristen","kristi","kristin","kristina","kristine","kristy","kurt","kyle",
    "lacey","lance","landon","larry","laura","lauren","laurie","lawrence","layla","lea",
    "leah","lee","leigh","lena","leo","leon","leonard","leroy","leslie","levi","lewis",
    "liam","lillian","lily","linda","lindsay","lindsey","lisa","lloyd","logan","lois",
    "lonnie","lora","loretta","lori","lorraine","louis","louise","lucas","lucia","lucille",
    "lucy","luis","luke","luna","lydia","lynn","mackenzie","madeline","madison","mae",
    "maggie","malcolm","mandy","marc","marcia","marcus","margaret","margie","maria","mariah",
    "marie","marilyn","mario","marion","marissa","marjorie","mark","marlene","marsha",
    "marshall","martha","martin","marvin","mary","mason","matt","matthew","maureen","max",
    "maxine","maya","megan","meghan","melanie","melinda","melissa","melody","mercedes",
    "meredith","mia","michael","michele","michelle","miguel","mike","mildred","miles",
    "mindy","miranda","misty","mitchell","molly","monica","monique","morgan","morris",
    "mya","myra","myrtle","nancy","naomi","natalie","natasha","nathan","nathaniel","neil",
    "nelson","nicholas","nick","nicole","nina","noah","noel","nolan","nora","norma","norman",
    "olivia","oscar","owen","paige","pam","pamela","pat","patricia","patrick","patsy",
    "patti","patty","paul","paula","pauline","pearl","peggy","penelope","penny","perry",
    "pete","peter","philip","phillip","phyllis","piper","priscilla","quinn","rachel","ralph",
    "ramona","randall","randy","ray","raymond","rebecca","regina","reginald","renee","rex",
    "rhonda","ricardo","richard","rick","ricky","riley","rita","rob","robert","roberta",
    "robin","robyn","rocky","rod","rodney","roger","ron","ronald","ronnie","rosa","rose",
    "rosemary","ross","roxanne","roy","ruby","rudy","russ","russell","ruth","ryan","rylee",
    "sabrina","sadie","sally","sam","samantha","samuel","sandra","sandy","sara","sarah",
    "savannah","scarlett","scott","sean","sebastian","seth","shane","shannon","shari","sharon",
    "shaun","shawn","sheila","shelby","shelly","sheri","sherri","sherry","shirley","sierra",
    "skylar","sonia","sophia","stacey","stacy","stanley","stella","stephanie","stephen",
    "steve","steven","stuart","sue","summer","susan","susie","suzanne","sydney","sylvia",
    "tabitha","tamara","tammy","tanya","tara","taylor","ted","teresa","terri","terry",
    "tessa","theresa","thomas","tiffany","tim","timothy","tina","todd","tom","tommy",
    "toni","tony","tonya","tracey","traci","tracy","travis","trenton","trevor","tricia",
    "trisha","trinity","troy","tyler","tyrone","valerie","vanessa","vera","vernon","veronica",
    "vicki","vickie","vicky","victor","victoria","vincent","violet","virginia","vivian",
    "wade","walter","wanda","warren","wayne","wendy","wesley","whitney","wilbur","willard",
    "william","willie","willow","willy","wilson","wyatt","xavier","yolanda","yvonne",
    "zachary","zoe","zoey",
}


def get_first_name(full_name):
    """Extract and validate first name from lead name.

    Returns the first word if it's a recognized first name (SSA data),
    otherwise returns 'there' (for company names like 'Bridgerow Blinds').
    """
    if not full_name or not full_name.strip():
        return "there"
    first_word = full_name.strip().split()[0]
    if first_word.lower() in COMMON_FIRST_NAMES:
        return first_word.capitalize()
    return "there"


def format_property_list_inline(properties):
    """Format properties as inline text: '{street_1} in {city_1} and {street_2} in {city_2}'.

    2 properties: '{street_1} in {city_1} and {street_2} in {city_2}'
    3+ properties: '{street_1} in {city_1}, {street_2} in {city_2}, and {street_3} in {city_3}'

    Uses property_address when it has a real street address (3+ comma parts).
    Falls back to canonical_name for city-only addresses like 'South Lyon, MI'.
    """
    items = []
    for p in properties:
        addr = p.get("property_address", "")
        canonical = p.get("canonical_name", "")
        parts = [part.strip() for part in addr.split(",")] if addr else []
        if len(parts) >= 3:
            # Full street address: '826 N Main St, Adrian, MI 49221' → '826 N Main St in Adrian'
            street = parts[0]
            city = parts[1]
            items.append(f"{street} in {city}")
        elif canonical:
            items.append(canonical)
        elif addr:
            items.append(addr)
        else:
            items.append(p.get("property_name", ""))
    if len(items) == 0:
        return ""
    elif len(items) == 1:
        return items[0]
    elif len(items) == 2:
        return f"{items[0]} and {items[1]}"
    else:
        return ", ".join(items[:-1]) + f", and {items[-1]}"


def create_gmail_draft(oauth, to_email, subject, body, cc=None, html_signature=""):
    """Create a Gmail draft. Single API call — no custom headers.

    Gmail strips custom X- headers when sending, so we don't set any.
    Sent emails are matched back to signals by thread_id (stored in jake_signals).
    """
    creds = Credentials(
        token=oauth["access_token"],
        refresh_token=oauth["refresh_token"],
        token_uri="https://oauth2.googleapis.com/token",
        client_id=oauth["client_id"],
        client_secret=oauth["client_secret"]
    )
    service = build('gmail', 'v1', credentials=creds)

    html_body = body.replace('\n', '<br>')
    if html_signature:
        html_body = html_body + '<br><br>' + html_signature
    message = MIMEText(html_body, 'html')
    message['to'] = to_email
    message['subject'] = subject
    if cc:
        message['cc'] = cc

    raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
    draft = service.users().drafts().create(
        userId='me',
        body={'message': {'raw': raw}}
    ).execute()

    return {
        "draft_id": draft['id'],
        "thread_id": draft['message']['threadId']
    }


def get_html_signature(source, template_used, sig_config):
    """Look up the HTML signature for a given source/template from the signer config."""
    signers = sig_config.get("signers", {})
    if not signers:
        return ""

    # Check template_used first (in-flight thread continuity)
    for prefix, signer_key in sig_config.get("template_prefix_to_signer", {}).items():
        if template_used == prefix or template_used.startswith(prefix):
            signer = signers.get(signer_key, {})
            if signer:
                return signer.get("html_signature", "")

    # Fall back to source classification
    src = source.lower()
    for group in sig_config.get("source_to_signer", {}).values():
        if src in group["sources"]:
            signer = signers.get(group["signer"], {})
            if signer:
                return signer.get("html_signature", "")

    # Default
    default_key = sig_config.get("default_signer", "larry")
    return signers.get(default_key, {}).get("html_signature", "")


def main(grouped_data: dict):
    standard_leads = grouped_data.get("standard_leads", [])
    info_requests = grouped_data.get("info_requests", [])
    drafts = []

    # Get Gmail OAuth credentials and signer config
    gmail_oauth = wmill.get_resource("f/switchboard/gmail_oauth")
    try:
        sig_config = json.loads(wmill.get_variable("f/switchboard/email_signatures"))
    except Exception:
        sig_config = {}

    for lead in standard_leads:
        first_name = get_first_name(lead["name"])
        email = lead["email"]
        phone = lead.get("phone", "")
        source = lead.get("source", "")
        source_type = lead.get("source_type", "")
        is_followup = lead.get("is_followup", False)
        properties = lead.get("properties", [])
        has_lead_magnet = any(p.get("lead_magnet") for p in properties)
        non_magnet_props = [p for p in properties if not p.get("lead_magnet")]
        is_commercial = source.lower() in ("crexi", "loopnet", "bizbuysell")
        is_residential_seller = source.lower() in ("seller hub", "social connect", "upnest")

        draft = {
            "name": lead["name"],
            "email": email,
            "phone": phone,
            "cc": "",
            "from_email": "teamgotcher@gmail.com",
            "source": source,
            "source_type": source_type,
            "is_new": lead.get("is_new", True),
            "is_followup": is_followup,
            "wiseagent_client_id": lead.get("wiseagent_client_id"),
            "properties": properties,
            "notification_message_ids": lead.get("notification_message_ids", [])
        }

        # --- Template selection (order matters) ---

        # 1. Realtor.com (residential buyer, signed Andrea)
        if source.lower() == "realtor.com":
            prop = properties[0] if properties else {}
            addr = prop.get("property_address") or prop.get("canonical_name", "your property")
            canonical = prop.get("canonical_name", addr)
            draft["email_subject"] = f"RE: Your Realtor.com inquiry in {canonical}"
            draft["email_body"] = f"Hey {first_name},\n\nI received your Realtor.com inquiry about {addr}. If you'd like more information, just let me know and I'll be more than happy to answer any questions you may have. Should you want to view the property, just let me know the best day and time that works for you and I'll get that scheduled. Keep in mind the sooner the better as properties are selling quick.\n\nIf you'd rather talk over the phone, my direct line is (734) 223-1015. Please do not hesitate to reach out with any questions or concerns."
            draft["sms_body"] = f"Hey {first_name}, this is Andrea. I received your Realtor.com inquiry about {addr}. If you'd like more information or to schedule a tour, just let me know the best day & time that works for you and I'll get that scheduled. Keep in mind the sooner, the better as properties sell quickly." if phone else None
            draft["template_used"] = "realtor_com"

        # 2. Residential seller (Seller Hub, UpNest, Top Producer, Social Connect — signed Andrea)
        elif is_residential_seller:
            prop = properties[0] if properties else {}
            addr = prop.get("property_address") or prop.get("canonical_name", "your property")
            canonical = prop.get("canonical_name", addr)
            draft["email_subject"] = f"RE: Your interest in {canonical}"
            draft["email_body"] = f"Hey {first_name},\n\nI got your information off of {source} when you checked out my property, {addr}. If you'd like more information, just let me know and I'll be more than happy to answer any questions you may have. Should you want to view the property, just let me know the best day and time that works for you and I'll get that scheduled. Keep in mind the sooner the better as properties are selling quick.\n\nIf you'd rather talk over the phone, my direct line is (734) 223-1015. Please do not hesitate to reach out with any questions or concerns."
            draft["sms_body"] = f"Hey {first_name}, this is Andrea from Resource Realty Group. I got your info when you checked out {addr}. If you'd like more information or to schedule a viewing, just let me know! My direct line is (734) 223-1015." if phone else None
            draft["template_used"] = "residential_seller"

        # 3. Lead magnet — all properties are lead_magnet (signed Larry for commercial)
        elif has_lead_magnet and not non_magnet_props:
            magnet = properties[0]
            canonical = magnet.get("canonical_name", "")
            addr = magnet.get("property_address") or canonical
            draft["email_subject"] = f"RE: Your Interest in {canonical}"
            draft["email_body"] = f"Hey {first_name},\n\nI got your information when you checked out my listing for {addr}. That property is no longer available, but we have some similar properties that might be a good fit depending on what you're looking for.\n\nIf you'd like to check out what we have, just let me know and I can send over some information. We also have some off-market properties that would require an NDA to be signed.\n\nIf you'd rather talk over the phone, my direct line is (734) 732-3789. Please do not hesitate to reach out with any questions or concerns."
            draft["sms_body"] = f"Hey {first_name}, this is Larry from Resource Realty Group. I saw you checked out {canonical}. That one's no longer available, but I have some similar properties. Let me know if you're interested! My direct line is (734) 732-3789." if phone else None
            draft["template_used"] = "lead_magnet"

        # 4-7. Commercial (Crexi/LoopNet) — signed Larry
        elif is_commercial:
            if len(properties) > 1:
                # Multi-property
                if is_followup:
                    # 4. commercial_multi_property_followup
                    draft["email_subject"] = "RE: Your Interest in Multiple Properties"
                    draft["email_body"] = f"Hey {first_name},\n\nI see you checked out a few more of my listings. If you'd like to check out more information on any of these, just let me know and I'll send over the OMs."
                    draft["sms_body"] = f"Hey {first_name}, I see you checked out a few more of my listings. Let me know if you'd like the OMs on any of them! - Larry" if phone else None
                    draft["template_used"] = "commercial_multi_property_followup"
                else:
                    # 5. commercial_multi_property_first_contact
                    prop_text = format_property_list_inline(non_magnet_props or properties)
                    draft["email_subject"] = "RE: Your Interest in Multiple Properties"
                    draft["email_body"] = f"Hey {first_name},\n\nI got your information off of {source} when you checked out {prop_text}.\n\nIf you'd like to check out more information on any of these, just let me know and I'll send over the OMs.\n\nAlternatively, we also have some off-market properties that might be a good fit, depending on what you're looking for. They would require an NDA to be signed, so just let me know and I can send one over to you.\n\nIf you'd rather talk over the phone, my direct line is (734) 732-3789. Please do not hesitate to reach out with any questions or concerns."
                    draft["sms_body"] = f"Hey {first_name}, this is Larry from Resource Realty Group. I saw you checked out a few of my properties on {source}. Let me know if you'd like more info on any of them! My direct line is (734) 732-3789." if phone else None
                    draft["template_used"] = "commercial_multi_property_first_contact"
            else:
                # Single property
                prop = properties[0] if properties else {}
                addr = prop.get("property_address") or prop.get("canonical_name", "the property")
                canonical = prop.get("canonical_name", addr)
                if is_followup:
                    # 6. commercial_followup_template
                    draft["email_subject"] = f"RE: Your Interest in {canonical}"
                    draft["email_body"] = f"Hey {first_name},\n\nI see you checked out another property - {addr}.\n\nIf you'd like to check out more information on this one, just let me know and I'll send over the OM."
                    draft["sms_body"] = f"Hey {first_name}, I see you checked out another property - {addr}. Let me know if you'd like the OM on this one! - Larry" if phone else None
                    draft["template_used"] = "commercial_followup_template"
                else:
                    # 7. commercial_first_outreach_template
                    draft["email_subject"] = f"RE: Your Interest in {canonical}"
                    draft["email_body"] = f"Hey {first_name},\n\nI got your information off of {source} when you checked out my property, {addr}.\n\nIf you'd like to check out more information, just let me know and I'll send over the OM so you can check it out.\n\nAlternatively, we also have some off-market properties that might be a good fit, depending on what you're looking for. They would require an NDA to be signed, so just let me know and I can send one over to you.\n\nIf you'd rather talk over the phone, my direct line is (734) 732-3789. Please do not hesitate to reach out with any questions or concerns."
                    draft["sms_body"] = f"Hey {first_name}, this is Larry from Resource Realty Group. I got your information off of {source} when you checked out my property, {addr}. If you'd like more info, just let me know and I'll send over the OM. My direct line is (734) 732-3789." if phone else None
                    draft["template_used"] = "commercial_first_outreach_template"

        # 8. Unknown source type — skip (no draft)
        else:
            continue

        # Look up HTML signature for this draft's source/template
        draft["html_signature"] = get_html_signature(source, draft.get("template_used", ""), sig_config)

        drafts.append(draft)

    # Now create Gmail drafts for each lead
    for draft in drafts:
        try:
            result = create_gmail_draft(
                gmail_oauth,
                draft["email"],
                draft["email_subject"],
                draft["email_body"],
                cc=draft.get("cc"),
                html_signature=draft.get("html_signature", "")
            )

            # Store Gmail draft info (thread_id is used for SENT matching)
            draft["gmail_draft_id"] = result["draft_id"]
            draft["gmail_message_id"] = None
            draft["gmail_thread_id"] = result["thread_id"]
            draft["draft_created_at"] = datetime.now(timezone.utc).isoformat()
            draft["draft_creation_success"] = True

        except Exception as e:
            draft["gmail_draft_id"] = None
            draft["gmail_message_id"] = None
            draft["gmail_thread_id"] = None
            draft["draft_created_at"] = datetime.now(timezone.utc).isoformat()
            draft["draft_creation_success"] = False
            draft["draft_creation_error"] = str(e)

        # Remove html_signature from draft — already baked into the Gmail draft
        draft.pop("html_signature", None)

    # Generate summary
    new_count = sum(1 for d in drafts if d.get("is_new"))
    existing_count = len(drafts) - new_count
    successful_drafts = sum(1 for d in drafts if d.get("draft_creation_success"))

    preflight = {
        "scan_complete": True,
        "parse_complete": True,
        "crm_lookup_complete": True,
        "property_match_complete": True,
        "drafts_complete": True,
        "gmail_drafts_created": successful_drafts,
        "total_leads": len(drafts),
        "new_contacts": new_count,
        "existing_contacts": existing_count,
        "info_requests": len(info_requests),
        "multi_property": grouped_data.get("multi_property_count", 0)
    }

    summary = f"Lead Intake: {len(drafts)} leads ready | {new_count} new, {existing_count} existing | {successful_drafts} drafts created | {len(info_requests)} info requests"

    return {
        "preflight_checklist": preflight,
        "drafts": drafts,
        "info_requests": info_requests,
        "summary": summary
    }
