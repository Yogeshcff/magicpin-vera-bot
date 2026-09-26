from __future__ import annotations
import re
from typing import Optional


def _pct(x):
    if x is None: return None
    return f"{abs(x)*100:.0f}%"

def _name(m):
    return m.get("identity", {}).get("owner_first_name") or m.get("identity", {}).get("name", "there")

def _biz(m): return m.get("identity", {}).get("name", "your business")
def _cat(c): return c.get("slug", "business")
def _active_offers(m): return [o.get("title") for o in m.get("offers", []) if o.get("status") == "active"]
def _find_digest(c, payload):
    top = payload.get("top_item_id") or payload.get("top_item", {}).get("id")
    for x in c.get("digest", []):
        if top and x.get("id") == top: return x
    return c.get("digest", [None])[0] if c.get("digest") else None

def _offer(m, keyword=None):
    offers = _active_offers(m)
    if keyword:
        for o in offers:
            if keyword.lower() in o.lower(): return o
    return offers[0] if offers else None

def _language(cust, merchant):
    return (cust or {}).get("identity", {}).get("language_pref") or "en"

def _merchant_message(name, body):
    return f"{name}, {body}"

def compose(category: dict, merchant: dict, trigger: dict, customer: Optional[dict] = None) -> dict:
    """Deterministic context-grounded Vera composer."""
    kind = trigger.get("kind", "")
    p = trigger.get("payload", {}) or {}
    name = _name(merchant)
    biz = _biz(merchant)
    cat = _cat(category)
    scope = trigger.get("scope", "merchant")
    suppression = trigger.get("suppression_key", trigger.get("id", kind))

    # Customer-facing messages first.
    if scope == "customer" and customer:
        cname = customer.get("identity", {}).get("name", "there")
        pref = customer.get("preferences", {}).get("preferred_slots") or customer.get("preferences", {}).get("preferred_time")
        offers = _active_offers(merchant)
        offer = offers[0] if offers else None

        if kind == "recall_due":
            service = str(p.get("service_due", "your regular service")).replace("_", " ")
            slots = p.get("available_slots", [])
            slot_text = ""
            if slots:
                slot_text = " Apke liye " + " ya ".join(s.get("label", "") for s in slots[:2]) + " available hain."
            price = f" {offer}." if offer else ""
            body = f"Hi {cname}, {biz} here. Your {service} recall is due around {p.get('due_date','soon')}.{slot_text}{price} Reply with the slot that works for you, or tell us another time."
            return {"body": body, "cta": "open_ended", "send_as": "merchant_on_behalf", "suppression_key": suppression, "rationale": "Recall reminder grounded in due date, customer identity and available booking slots."}

        if kind in {"customer_lapsed_hard", "customer_lapsed_soft", "winback_eligible"}:
            days = p.get("days_since_last_visit") or p.get("days_since_expiry")
            focus = p.get("previous_focus")
            detail = f" It's been {days} days since your last visit." if days is not None else ""
            focus_text = f" We can pick up your {focus} goal again." if focus else ""
            price = f" {offer} is currently active." if offer else ""
            body = f"Hi {cname}, {biz} here.{detail}{focus_text}{price} If you'd like to restart, reply YES and we'll help with the next step."
            return {"body": body, "cta": "yes_stop", "send_as": "merchant_on_behalf", "suppression_key": suppression, "rationale": "Winback uses the customer's lapse duration and prior goal without guilt or invented claims."}

        if kind == "wedding_package_followup":
            body = f"Hi {cname}, {biz} here. Your wedding date is {p.get('wedding_date')}, and your next-step window is open for the {p.get('next_step_window_open','bridal prep')}. Want us to help plan the next appointment? Reply YES."
            return {"body": body, "cta": "yes_stop", "send_as": "merchant_on_behalf", "suppression_key": suppression, "rationale": "Bridal follow-up uses the recorded wedding date and next-step window."}

        if kind == "trial_followup":
            opts = p.get("next_session_options", [])
            slots = ", ".join(x.get("label", "") for x in opts[:2])
            body = f"Hi {cname}, {biz} here. Following up after your trial on {p.get('trial_date','recently')}. {('We have '+slots+' available.' if slots else 'We can help with the next session.')} Reply YES if you'd like to continue."
            return {"body": body, "cta": "yes_stop", "send_as": "merchant_on_behalf", "suppression_key": suppression, "rationale": "Trial follow-up references the actual trial date and next available session."}

        if kind == "chronic_refill_due":
            mols = ", ".join(p.get("molecule_list", []))
            runout = p.get("stock_runs_out_iso", "soon")
            delivery = " Delivery address is already saved." if p.get("delivery_address_saved") else ""
            body = f"Hi {cname}, {biz} here. Your refill for {mols} is due before {runout}.{delivery} Reply YES if you'd like us to prepare the refill."
            return {"body": body, "cta": "yes_stop", "send_as": "merchant_on_behalf", "suppression_key": suppression, "rationale": "Refill reminder is based only on the listed medicines, run-out date and saved delivery status."}

    # Merchant-facing trigger handlers.
    if kind == "research_digest":
        d = _find_digest(category, p) or {}
        title = d.get("title", "this week's category research")
        source = d.get("source", "the category digest")
        stats = []
        for k in ("trial_n", "delta_yoy", "percent_change"):
            if k in d: stats.append(f"{k.replace('_',' ')} {d[k]}")
        extra = ", ".join(stats)
        body = _merchant_message(name, f"{title} landed in the {source} digest" + (f" ({extra})" if extra else "") + ". It looks relevant to your current business. Want me to turn the useful point into a customer-ready post?")
        return {"body": body, "cta": "open_ended", "send_as": "vera", "suppression_key": suppression, "rationale": "Research trigger tied to a concrete digest item and offered as a useful merchant artifact."}

    if kind == "regulation_change":
        d = _find_digest(category, p) or {}
        title = d.get("title", "a regulatory update")
        deadline = p.get("deadline_iso")
        body = _merchant_message(name, f"Heads-up: {title}." + (f" The recorded deadline is {deadline}." if deadline else "") + " Want me to turn the change into a short compliance checklist for your team?")
        return {"body": body, "cta": "yes_stop", "send_as": "vera", "suppression_key": suppression, "rationale": "Compliance message cites the supplied regulatory item and deadline, then offers a concrete checklist."}

    if kind == "perf_dip":
        metric = p.get("metric", "metric")
        delta = p.get("delta_pct")
        baseline = p.get("vs_baseline")
        peer = category.get("peer_stats", {})
        peer_ctr = peer.get("avg_ctr")
        detail = f"{_pct(delta)}" if delta is not None else "a decline"
        baseline_text = f" vs a baseline of {baseline}" if baseline is not None else ""
        peer_text = f" Your current CTR is {merchant.get('performance',{}).get('ctr')} vs peer avg {peer_ctr}." if metric == "calls" and peer_ctr else ""
        body = _merchant_message(name, f"{metric.capitalize()} are down {detail} over {p.get('window','7d')}{baseline_text}.{peer_text} Want me to diagnose the likely bottleneck from your profile and draft one testable fix?")
        return {"body": body, "cta": "open_ended", "send_as": "vera", "suppression_key": suppression, "rationale": "Performance alert uses the exact metric change and baseline from the trigger."}

    if kind == "renewal_due":
        body = _merchant_message(name, f"Your {p.get('plan', merchant.get('subscription',{}).get('plan','plan'))} renewal is in {p.get('days_remaining','a few')} days; the recorded renewal amount is ₹{p.get('renewal_amount','—')}. Want me to prepare a renewal checklist?")
        return {"body": body, "cta": "yes_stop", "send_as": "vera", "suppression_key": suppression, "rationale": "Renewal message uses the exact remaining days, plan and amount supplied."}

    if kind == "festival_upcoming":
        fest, days = p.get("festival", "the upcoming festival"), p.get("days_until")
        offers = _active_offers(merchant)
        offer_text = f" Your active offer is {offers[0]}." if offers else ""
        body = _merchant_message(name, f"{fest} is {days} days away.{offer_text} Want me to draft a simple {cat}-specific festival post using only your active offer?")
        return {"body": body, "cta": "open_ended", "send_as": "vera", "suppression_key": suppression, "rationale": "Festival trigger is tied to the supplied countdown and existing offer catalog."}

    if kind == "curious_ask_due":
        ask = p.get("ask_template", "what is worth trying this week")
        body = _merchant_message(name, f"Quick operator question: {ask.replace('_',' ')}? I can answer it using your current profile and the category signals.")
        return {"body": body, "cta": "open_ended", "send_as": "vera", "suppression_key": suppression, "rationale": "Curious-ask cadence invites a low-friction, category-relevant operator question."}

    if kind == "winback_eligible":
        body = _merchant_message(name, f"Your subscription expired {p.get('days_since_expiry','')} days ago, while performance is {abs(p.get('perf_dip_pct',0))*100:.0f}% below the reference window and {p.get('lapsed_customers_added_since_expiry',0)} lapsed customers have accumulated since expiry. Want a concrete win-back plan built around your current offers?")
        return {"body": body, "cta": "yes_stop", "send_as": "vera", "suppression_key": suppression, "rationale": "Win-back uses expiry age, performance change and lapsed-customer count."}

    if kind == "ipl_match_today":
        offer = _offer(merchant)
        match, venue, time = p.get("match"), p.get("venue"), p.get("match_time_iso")
        body = _merchant_message(name, f"{match} is at {venue} today ({time})." + (f" Your active offer is {offer}." if offer else "") + " Want me to draft a match-day delivery message using what you already sell?")
        return {"body": body, "cta": "open_ended", "send_as": "vera", "suppression_key": suppression, "rationale": "Match-day message anchors on the supplied match, venue/time and active offer."}

    if kind == "review_theme_emerged":
        body = _merchant_message(name, f"A review theme is rising: {p.get('occurrences_30d',0)} reviews in 30 days mention {p.get('theme','the same issue')} and the trend is {p.get('trend','changing')}. One recent customer wording was: ‘{p.get('common_quote','') }’. Want me to draft a response + operational fix?")
        return {"body": body, "cta": "yes_stop", "send_as": "vera", "suppression_key": suppression, "rationale": "Review alert cites occurrence count, theme, trend and supplied customer wording."}

    if kind == "milestone_reached":
        metric, now, target = p.get("metric", "metric"), p.get("value_now"), p.get("milestone_value")
        body = _merchant_message(name, f"You’re at {now} {metric.replace('_',' ')} with {target} as the next milestone." + (f" Want me to draft a review-request message?" if metric == "review_count" else " Want me to turn this milestone into a simple customer-facing post?"))
        return {"body": body, "cta": "open_ended", "send_as": "vera", "suppression_key": suppression, "rationale": "Milestone uses the current and target values from the trigger."}

    if kind == "active_planning_intent":
        topic = p.get("intent_topic", "the plan")
        last = p.get("merchant_last_message", "")
        if "corporate" in topic or "thali" in topic:
            offer = _offer(merchant, "thali") or "your active thali offer"
            body = _merchant_message(name, f"Here’s a starter corporate-thali version built around {offer}: define a simple bulk-order tier, a cutoff time, and a delivery window using your actual operating constraints. Want me to draft the customer-facing 3-line WhatsApp next?")
        elif "kids_yoga" in topic:
            offers = _active_offers(merchant)
            offer_text = ", ".join(offers[:2]) if offers else "your current membership offers"
            members = merchant.get("customer_aggregate", {}).get("total_active_members")
            body = _merchant_message(name, f"For the kids-yoga program, I’d build the draft around your existing offers ({offer_text})" + (f" and your current base of {members} active members" if members else "") + ". Want me to turn that into a 1-page offer with schedule and parent CTA?")
        else:
            body = _merchant_message(name, f"Yes — continuing from your request about {topic.replace('_',' ')}. I can turn the idea into a concrete offer with pricing, timing and a customer message. Want me to draft that now?")
        return {"body": body, "cta": "open_ended", "send_as": "vera", "suppression_key": suppression, "rationale": "Active planning is handled as intent continuation rather than another discovery question."}

    if kind == "seasonal_perf_dip":
        delta = _pct(p.get("delta_pct")) or "a decline"
        season = p.get("season_note", "the current seasonal window").replace("_", " ")
        members = merchant.get("customer_aggregate", {}).get("active_members") or merchant.get("customer_aggregate", {}).get("total_unique_ytd")
        body = _merchant_message(name, f"Views are down {delta} this week, but this trigger marks the dip as expected for {season}." + (f" You still have {members} active/known customers in the current profile." if members else "") + " Want me to draft a retention-focused action instead of chasing acquisition during the dip?")
        return {"body": body, "cta": "open_ended", "send_as": "vera", "suppression_key": suppression, "rationale": "Seasonal dip is reframed using the explicit expected-season flag rather than treating it as a crisis."}

    if kind in {"customer_lapsed_hard", "customer_lapsed_soft"}:
        body = _merchant_message(name, f"A customer has been inactive for {p.get('days_since_last_visit','')} days" + (f" after focusing on {p.get('previous_focus')}." if p.get('previous_focus') else ".") + " Want me to draft a no-pressure win-back message?")
        return {"body": body, "cta": "yes_stop", "send_as": "vera", "suppression_key": suppression, "rationale": "Merchant-side lapse alert uses the supplied customer lapse details and proposes a concrete draft."}

    if kind == "trial_followup":
        body = _merchant_message(name, f"A trial follow-up is due for the customer who trialled on {p.get('trial_date','the recorded date')}. Next available option: {', '.join(x.get('label','') for x in p.get('next_session_options',[])[:2])}. Want me to draft the follow-up?")
        return {"body": body, "cta": "yes_stop", "send_as": "vera", "suppression_key": suppression, "rationale": "Trial follow-up is grounded in the trial date and supplied next-session option."}

    if kind == "supply_alert":
        batches = ", ".join(p.get("affected_batches", []))
        body = _merchant_message(name, f"Urgent supply alert: {p.get('molecule','the listed medicine')} — affected batches {batches} from {p.get('manufacturer','the listed manufacturer')}. Please isolate/check those batches against your stock records. Want me to format a staff/customer notice from the supplied recall details?")
        return {"body": body, "cta": "yes_stop", "send_as": "vera", "suppression_key": suppression, "rationale": "Safety alert names only the molecule, affected batches and manufacturer provided by the trigger."}

    if kind == "category_seasonal":
        trends = ", ".join(str(x).replace("_", " ") for x in p.get("trends", [])[:3])
        body = _merchant_message(name, f"The {p.get('season','current')} category signal shows {trends or 'a seasonal demand shift'}." + (" Shelf action is specifically recommended." if p.get("shelf_action_recommended") else "") + " Want me to map that to one concrete action using your current offers and profile?")
        return {"body": body, "cta": "open_ended", "send_as": "vera", "suppression_key": suppression, "rationale": "Seasonal category signal is offered as a context-grounded action rather than generic promotion."}

    if kind == "gbp_unverified":
        body = _merchant_message(name, "Your Google Business Profile is still marked unverified in the current context. That can limit how reliably customers see the listing. Want a short verification checklist?")
        return {"body": body, "cta": "yes_stop", "send_as": "vera", "suppression_key": suppression, "rationale": "Uses the explicit verification state and offers a concrete checklist."}

    if kind == "cde_opportunity":
        body = _merchant_message(name, "There’s a category opportunity in the current CDE signal. Want me to turn the supplied insight into one concrete merchant action and a draft customer message?")
        return {"body": body, "cta": "open_ended", "send_as": "vera", "suppression_key": suppression, "rationale": "CDE opportunity is treated as an actionable category signal."}

    if kind == "competitor_opened":
        competitor = p.get("competitor_name") or p.get("name") or "a new nearby competitor"
        distance = p.get("distance_km")
        their_offer = p.get("their_offer")
        body = _merchant_message(name, f"A new competitor signal is recorded: {competitor}" + (f" about {distance} km away" if distance else "") + (f", offering {their_offer}." if their_offer else ".") + " I’d compare your current offer/profile before changing price. Want me to draft that comparison?")
        return {"body": body, "cta": "open_ended", "send_as": "vera", "suppression_key": suppression, "rationale": "Competitor message uses only supplied competitor facts and proposes a concrete response."}

    if kind == "perf_spike":
        metric = p.get("metric", "performance")
        delta = p.get("delta_pct")
        body = _merchant_message(name, f"{metric.capitalize()} are up {_pct(delta) if delta is not None else 'sharply'} in the current window. Want me to identify what changed and turn the strongest signal into a repeatable action?")
        return {"body": body, "cta": "open_ended", "send_as": "vera", "suppression_key": suppression, "rationale": "Positive performance alert uses the supplied metric and change."}

    if kind == "dormant_with_vera":
        days = p.get("days_inactive") or p.get("days_since_last_message") or p.get("days_since_last_merchant_message") or 14
        topic = p.get("last_topic")
        body = _merchant_message(name, f"We haven’t had a Vera conversation in {days} days" + (f", since {topic.replace('_',' ')}." if topic else ".") + " Rather than send a generic update, I can use your current profile to pick one useful issue to work on. Want that?")
        return {"body": body, "cta": "open_ended", "send_as": "vera", "suppression_key": suppression, "rationale": "Dormancy trigger acknowledges the inactivity window and avoids generic promotional outreach."}

    if kind == "appointment_tomorrow":
        body = _merchant_message(name, f"You have an appointment tomorrow in the current schedule. Want me to draft a concise WhatsApp reminder using the booking details?")
        return {"body": body, "cta": "yes_stop", "send_as": "vera", "suppression_key": suppression, "rationale": "Appointment trigger is handled as a concrete reminder workflow."}

    # Safe generic fallback: factual, trigger-specific, no invented numbers.
    body = _merchant_message(name, f"A {kind.replace('_',' ')} trigger is active for {biz}. I can turn the supplied context into one concrete next step. Want me to draft it?")
    return {"body": body, "cta": "open_ended", "send_as": "vera", "suppression_key": suppression, "rationale": "Fallback stays grounded in the trigger kind and avoids unsupported facts."}
