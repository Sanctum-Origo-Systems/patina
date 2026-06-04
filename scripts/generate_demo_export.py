"""Generate a synthetic Slack export for demo purposes.

Creates a realistic 4-week message history with fictional characters
that demonstrates: entity extraction, belief building, trust scoring,
belief decay, contradiction detection, autonomy earning, and style drafting.

Usage:
    python scripts/generate_demo_export.py [--output demo-export.zip]
"""

import json
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

# --- Characters ---

USERS = {
    "U001": {"real_name": "Alexis Williams", "name": "alexisw"},
    "U002": {"real_name": "Maya Patel", "name": "mayap"},
    "U003": {"real_name": "Jordan Kim", "name": "jordank"},
    "U004": {"real_name": "Sam O'Brien", "name": "samob"},
    "U005": {"real_name": "Atlas CI Bot", "name": "atlas-ci-bot"},
    "U006": {"real_name": "Priya Sharma", "name": "priyas"},
    "U007": {"real_name": "Kai Robertson", "name": "kair"},
    "U008": {"real_name": "Dana Torres", "name": "danat"},
    "U999": {"real_name": "You (owner)", "name": "owner"},
}

CHANNELS = {
    "C001": {"name": "engineering-leads"},
    "C002": {"name": "project-atlas"},
    "C003": {"name": "general"},
    "C004": {"name": "ci-notifications"},
}

# --- Timeline: 4 weeks of messages ---

def _ts(base: datetime, day_offset: int, hour: int, minute: int = 0) -> str:
    dt = base + timedelta(days=day_offset, hours=hour, minutes=minute)
    return f"{dt.timestamp():.6f}"


def generate_messages(base_date: datetime) -> dict[str, list[dict]]:
    """Generate messages organized by channel/date for Slack export format."""
    messages_by_channel_date: dict[str, dict[str, list[dict]]] = {}

    def add(channel_name: str, user: str, text: str, day: int, hour: int, minute: int = 0, thread_ts: str | None = None, reactions: list | None = None):
        ts = _ts(base_date, day, hour, minute)
        msg = {"user": user, "text": text, "ts": ts, "type": "message"}
        if thread_ts:
            msg["thread_ts"] = thread_ts
        if reactions:
            msg["reactions"] = reactions

        date_str = (base_date + timedelta(days=day)).strftime("%Y-%m-%d")
        if channel_name not in messages_by_channel_date:
            messages_by_channel_date[channel_name] = {}
        if date_str not in messages_by_channel_date[channel_name]:
            messages_by_channel_date[channel_name][date_str] = []
        messages_by_channel_date[channel_name][date_str].append(msg)
        return ts

    # =========================================================================
    # WEEK 1: Establishing relationships and initial claims
    # =========================================================================

    # Day 0 - Monday: Alexis sets context
    add("engineering-leads", "U001", "Team, we're kicking off Project Atlas this week. I'll be leading the architecture review. Target launch: end of Q3.", 0, 9)
    add("engineering-leads", "U001", "Key stakeholders: Maya on product, Jordan on backend, Priya's team on infra.", 0, 9, 5)
    add("engineering-leads", "U006", "I'll have the infra provisioning ready by Wednesday. Running on us-west-2.", 0, 9, 15)

    # Day 0 - DMs establishing trust
    t1 = add("dm-U001", "U001", "Hey, wanted to give you a heads up — we're getting pressure from Dana to ship Atlas early. Q3 target might move to mid-August.", 0, 10)
    add("dm-U001", "U999", "Thanks for the heads up Alexis. What's driving the acceleration?", 0, 10, 5, thread_ts=t1)
    add("dm-U001", "U001", "Board meeting in September. Dana wants a demo-ready version before then. I think it's doable if we scope correctly.", 0, 10, 10, thread_ts=t1)

    # Day 1 - Maya product context
    add("project-atlas", "U002", "Shared the PRD for Atlas in the team drive. Key differentiator: we're going with a graph-based approach instead of traditional RDBMS.", 1, 11)
    add("project-atlas", "U003", "I reviewed the PRD. The graph approach makes sense for our relationship queries. I can prototype the schema by Thursday.", 1, 11, 30)
    add("project-atlas", "U002", "Perfect Jordan. Let's sync Thursday PM to review your prototype.", 1, 11, 35)

    # Day 1 - Sam external partner
    add("dm-U004", "U004", "Hi there! Following up on our partnership discussion from last month. We've finalized the API spec on our end. When can we schedule the integration review?", 1, 14)

    # Day 2 - Bot messages (for auto-dismiss)
    add("ci-notifications", "U005", "Build #4521 passed. All 847 tests green. Deploy to staging complete.", 2, 6)
    add("ci-notifications", "U005", "Build #4522 passed. All 847 tests green. Deploy to staging complete.", 2, 8)
    add("ci-notifications", "U005", "Build #4523 FAILED. 2 tests failing in auth module. See details: http://ci.internal/build/4523", 2, 14)

    # Day 2 - Jordan technical depth
    t2 = add("dm-U003", "U003", "Quick question — for the graph schema, should we go with Neo4j or stick with PostgreSQL + adjacency list? I've used both.", 2, 15)
    add("dm-U003", "U999", "What's the query pattern? If it's mostly traversals (2+ hops), Neo4j. If it's mixed read/write with some joins, Postgres is simpler to operate.", 2, 15, 10, thread_ts=t2)
    add("dm-U003", "U003", "Mostly traversals — finding related entities within 3 hops, relationship scoring. Neo4j it is. Thanks.", 2, 15, 15, thread_ts=t2)

    # Day 3 - Priya infra update
    add("project-atlas", "U006", "Infrastructure is provisioned. Neo4j cluster running on 3 nodes in us-west-2. Connection strings in the secrets manager.", 3, 10)
    add("project-atlas", "U003", "Connected successfully. Schema migration running now.", 3, 10, 30)

    # Day 3 - Kai (new person) first appearance
    add("general", "U007", "Hey everyone! I'm Kai, just joined the platform team this week. Previously was at DataScale working on graph databases. Excited to contribute to Atlas!", 3, 11)
    add("general", "U001", "Welcome Kai! Great timing — we could use your graph expertise. <@U003> can you loop Kai into the schema discussion?", 3, 11, 15)

    # Day 4 - Dana skip-level (rare but important)
    add("dm-U008", "U008", "I've been reviewing the Atlas proposal. Strong work on the architecture. One concern: the mid-August timeline feels aggressive given the team size. What's your honest read?", 4, 16)
    add("dm-U008", "U999", "Honest read: technically achievable if we keep scope tight. Risk is the integration with Sam's external API — that's the unknown. I'd buffer 2 weeks.", 4, 16, 20)
    add("dm-U008", "U008", "Good. I trust your judgment on this. I'll communicate end of August externally. Keep me posted if anything shifts.", 4, 16, 30)

    # Day 4 - More bot noise
    add("ci-notifications", "U005", "Build #4530 passed. All 849 tests green. Deploy to staging complete.", 4, 7)
    add("ci-notifications", "U005", "Build #4531 passed. All 849 tests green. Deploy to staging complete.", 4, 18)

    # Day 5 - Friday: More DM exchanges (trust-building cadence)
    t_a1 = add("dm-U001", "U001", "End of week check — are we on track for the Thursday schema review?", 5, 16)
    add("dm-U001", "U999", "Yes. Jordan's prototype is solid. I'll prep the review deck over the weekend.", 5, 16, 3, thread_ts=t_a1)
    add("dm-U001", "U001", "Perfect. Have a good weekend.", 5, 16, 5, thread_ts=t_a1)

    # Day 5 - Maya sends something user deprioritizes
    add("dm-U002", "U002", "Also, when you get a chance — thoughts on whether we should add a dark mode toggle to the entity view? Low priority but the design team asked.", 5, 11)

    # Day 5 - General channel noise
    add("general", "U006", "Reminder: office closed Monday for maintenance. WFH day.", 5, 9)
    add("general", "U003", "Has anyone used the new Grafana dashboards? The Atlas metrics look great.", 5, 14)
    add("general", "U007", "Not yet but I'll check them out! Are they linked from the wiki?", 5, 14, 10)
    add("general", "U003", "Yeah, under Platform > Monitoring > Atlas. Direct link: http://grafana.internal/d/atlas-overview", 5, 14, 15)

    # Day 6 - Weekend: bot still posting
    add("ci-notifications", "U005", "Build #4533 passed. All 849 tests green. Deploy to staging complete.", 6, 3)
    add("ci-notifications", "U005", "Build #4534 passed. All 849 tests green. Deploy to staging complete.", 6, 15)

    # =========================================================================
    # WEEK 2: Claims reinforced, trust building
    # =========================================================================

    # Day 7 - Monday standup
    add("project-atlas", "U001", "Atlas standup: Jordan has the schema working. Priya's infra is solid. Maya, where are we on the UX flows?", 7, 9)
    add("project-atlas", "U002", "UX mocks are 80% done. Sharing by EOD. One concern: the search experience needs to handle 10k+ entities smoothly.", 7, 9, 10)
    add("project-atlas", "U003", "I indexed the graph for search. Sub-100ms for up to 50k nodes. Should be fine.", 7, 9, 15)

    # Day 7 - Alexis claim reinforcement (title/role)
    add("engineering-leads", "U001", "Reminder: as VP of Engineering, I'm accountable for the Atlas timeline to the board. Let's not slip.", 7, 14)

    # Day 8 - Commitment from user
    t3 = add("dm-U002", "U002", "Can you review my UX mocks before I share with the team? Want your perspective on the entity detail view.", 8, 10)
    add("dm-U002", "U999", "Sure, I'll review them by tomorrow morning. Send me the link.", 8, 10, 15, thread_ts=t3)
    add("dm-U002", "U002", "Sent! It's in the Atlas folder. Thanks 🙏", 8, 10, 20, thread_ts=t3)

    # Day 9 - Kai proving value
    add("project-atlas", "U007", "I noticed the Neo4j schema doesn't have decay on the confidence scores. At DataScale we found that time-weighted confidence prevents stale data from dominating. Want me to add it?", 9, 11)
    add("project-atlas", "U003", "Great catch Kai. Yes please — that aligns with our belief decay requirements from the PRD.", 9, 11, 20)
    add("project-atlas", "U001", "This is exactly why we brought you on. Go for it.", 9, 11, 25)

    # Day 9 - Sam follow-up (low frequency, still engaged)
    add("dm-U004", "U004", "Just checking in — were you able to review our API spec? No rush, just want to make sure it didn't get lost.", 9, 15)
    add("dm-U004", "U999", "Reviewing now. The auth flow looks solid. I have a question about the webhook retry policy — do you support exponential backoff?", 9, 16)
    add("dm-U004", "U004", "Yes, exponential with jitter. Max 5 retries over 30 minutes. Documented in section 4.2.", 9, 16, 10)

    # Day 10 - More bot messages
    add("ci-notifications", "U005", "Build #4545 passed. All 852 tests green. Deploy to staging complete.", 10, 7)
    add("ci-notifications", "U005", "Build #4546 passed. All 852 tests green. Deploy to staging complete.", 10, 12)
    add("ci-notifications", "U005", "Build #4547 passed. All 852 tests green. Deploy to staging complete.", 10, 19)

    # Day 10 - Jordan deep technical discussion
    t_j1 = add("dm-U003", "U003", "Been thinking about the traversal performance. Our worst case is 3-hop queries on highly connected nodes. Average fanout is 15 — that's 3375 nodes to visit.", 10, 15)
    add("dm-U003", "U999", "That's manageable with proper indexing. Are you caching the hot paths? The top 50 entities probably account for 80% of traversals.", 10, 15, 10, thread_ts=t_j1)
    add("dm-U003", "U003", "Good call. I'll add a TTL cache for frequent paths. Redis or in-memory?", 10, 15, 15, thread_ts=t_j1)
    add("dm-U003", "U999", "In-memory for now. Keep it simple. We can move to Redis if we scale past a single node.", 10, 15, 20, thread_ts=t_j1)

    # Day 10 - Priya operational update
    add("project-atlas", "U006", "Monitoring alert: Neo4j memory usage at 72%. Normal for our dataset size but I'm watching it. Will add memory if it crosses 85%.", 10, 16)

    # Day 11 - User acts fast on Alexis (trust signal)
    t4 = add("dm-U001", "U001", "Quick favor — can you pull the Atlas metrics dashboard together before Dana's review on Friday? Need: entity count growth, query latency p95, uptime.", 11, 9)
    add("dm-U001", "U999", "On it. I'll have it ready by EOD Thursday.", 11, 9, 5, thread_ts=t4)
    add("dm-U001", "U001", "You're the best. Dana specifically asked for the growth curve.", 11, 9, 10, thread_ts=t4)

    # Day 11 - User responds slowly to Maya (relative trust signal)
    add("dm-U002", "U002", "Hey, one more thing — can you also look at the onboarding flow? It's in the same folder. Would love feedback by Friday.", 11, 10)

    # Day 11 - Sam relationship maintenance
    add("dm-U004", "U004", "Quick update from our side: we've added the exponential backoff docs to section 4.2 as discussed. Also increased the webhook payload limit to 5MB. Should cover your batch sync use case.", 11, 14)
    add("dm-U004", "U999", "Great, that covers it. I'll update our integration config. We should be ready for the joint test next week.", 11, 14, 20)

    # Day 12 - More general channel
    add("general", "U002", "Team lunch at the Thai place tomorrow? Booking for 12:30.", 12, 16)
    add("general", "U003", "I'm in!", 12, 16, 5)
    add("general", "U007", "Count me in too 🙋", 12, 16, 8)
    add("general", "U006", "Can't tomorrow — have a vendor call. Next time!", 12, 16, 15)

    # Day 12 - More bot noise
    add("ci-notifications", "U005", "Build #4550 passed. All 852 tests green. Deploy to staging complete.", 12, 8)
    add("ci-notifications", "U005", "Build #4551 passed. All 853 tests green. Deploy to staging complete.", 12, 17)

    # Day 13 - Kai showing initiative
    add("project-atlas", "U007", "I wrote a runbook for the Neo4j cluster ops — backup, restore, scaling. Added it to the wiki under Platform > Operations > Atlas.", 13, 10)
    add("project-atlas", "U006", "This is great Kai, exactly what we needed. I'll review and add the monitoring sections.", 13, 10, 20)

    # Day 13 - User style exemplars (longer form)
    add("engineering-leads", "U999", "Quick update on Atlas: schema is stable, performance is within targets, and we've added operational runbooks. The team is executing well. Main risk remains the external integration timeline — Sam's team is ready on their end, we need to schedule the joint test.", 13, 14)

    # Day 13 - Alexis reinforcing her role
    add("engineering-leads", "U001", "Good update. I'll flag the integration timeline in my VP sync tomorrow. Let's make sure we don't let that slip.", 13, 14, 15)

    # =========================================================================
    # WEEK 3: Belief decay + contradiction + autonomy earning
    # =========================================================================

    # Day 14 - Alexis CONTRADICTS earlier claim (deadline shift)
    add("engineering-leads", "U001", "Update on Atlas timeline: after discussing with Dana, we're pushing launch to end of September. The August target was too aggressive.", 14, 9)
    # ^ This contradicts Day 0: "Target launch: end of Q3" and Day 4: "mid-August"

    # Day 14 - Evidence that user dismissed bot messages consistently (autonomy signal)
    add("ci-notifications", "U005", "Build #4560 passed. All 855 tests green. Deploy to staging complete.", 14, 6)
    add("ci-notifications", "U005", "Build #4561 passed. All 855 tests green. Deploy to staging complete.", 14, 9)
    add("ci-notifications", "U005", "Build #4562 passed. All 855 tests green. Deploy to staging complete.", 14, 14)
    add("ci-notifications", "U005", "Build #4563 passed. All 855 tests green. Deploy to staging complete.", 14, 19)

    # Day 15 - Priya shares something that will decay
    add("project-atlas", "U006", "FYI: running on t3.xlarge instances for now. Will resize to r6g.2xlarge before launch.", 15, 10)
    # ^ This claim about instance type will be outdated by week 4

    # Day 16 - Kai's expertise solidifies
    add("project-atlas", "U007", "Pushed the confidence decay implementation. Each claim now has a half-life based on its source reliability. High-confidence claims from direct observation decay slower than inferred ones.", 16, 14)
    add("project-atlas", "U001", "Kai, this is excellent work. Clean implementation. Jordan, can you code review?", 16, 14, 20)
    add("project-atlas", "U003", "Already reviewing. LGTM — merging.", 16, 14, 30)

    # Day 16 - User sent messages (for style exemplars)
    add("project-atlas", "U999", "Looks good to me. The decay curve parameters might need tuning once we have production data, but the architecture is solid. Ship it.", 16, 15)
    add("dm-U001", "U999", "Alexis — heads up, Kai is crushing it. The belief decay impl is exactly what we needed. Good hire.", 16, 15, 30)
    add("dm-U003", "U999", "Jordan, nice review turnaround. Quick question: should we add a migration path for existing claims that don't have decay rates yet?", 16, 16)

    # Day 16 - Priya asks for clarification
    t_p1 = add("dm-U006", "U006", "For the load test next week — what's our target? 10k concurrent entity queries or 50k?", 16, 16, 30)
    add("dm-U006", "U999", "50k. That's 3x our projected month-one load. If it holds at p95 < 200ms, we're good.", 16, 16, 40, thread_ts=t_p1)
    add("dm-U006", "U006", "Got it. I'll configure the load generator for 50k. Results by Thursday.", 16, 16, 45, thread_ts=t_p1)

    # Day 17 - More user sent messages (style diversity)
    add("dm-U004", "U999", "Sam — reviewed the full API spec. Looks solid. Two minor concerns: 1) the rate limit of 100 req/s might be tight during bulk sync, 2) webhook payload size limit isn't documented. Otherwise, good to proceed.", 17, 10)
    add("dm-U008", "U999", "Dana — quick update: Atlas is tracking well. Kai's contribution on belief decay saved us ~2 weeks. September launch looking solid. Will send formal status Friday.", 17, 14)

    # Day 17 - Jordan and Kai collaborating (relationship signal)
    add("project-atlas", "U003", "Kai and I paired on the confidence scoring algorithm today. His DataScale experience with time-weighted graphs was super helpful.", 17, 17)
    add("project-atlas", "U007", "Great pairing session! Jordan's system design instincts + my graph algorithms background = good combo.", 17, 17, 10)

    # Day 17 - General channel noise
    add("general", "U006", "Anyone else having VPN issues this morning? Can't reach the staging cluster.", 17, 8)
    add("general", "U003", "Same here. IT said they're doing maintenance until 10am.", 17, 8, 5)
    add("general", "U007", "Working fine for me — I'm on the backup VPN endpoint.", 17, 8, 10)

    # Day 18 - Maya needs response (tests priority)
    add("dm-U002", "U002", "Hey! Did you get a chance to look at the onboarding flow? Design review is Monday and I need to finalize.", 18, 9)

    # Day 18 - Bot continues
    add("ci-notifications", "U005", "Build #4565 passed. All 856 tests green. Deploy to staging complete.", 18, 7)
    add("ci-notifications", "U005", "Build #4566 passed. All 856 tests green. Deploy to staging complete.", 18, 13)

    # Day 19 - Alexis DM (fast response from user = trust)
    t_a2 = add("dm-U001", "U001", "Dana's exec review moved to next Wednesday. Can you update the metrics deck to include last week's numbers?", 19, 10)
    add("dm-U001", "U999", "Done. Updated with this week's numbers: 8.5k entities, p95 at 72ms, 99.97% uptime. Deck is in the shared folder.", 19, 10, 8, thread_ts=t_a2)
    add("dm-U001", "U001", "Lightning fast as always. Thanks.", 19, 10, 12, thread_ts=t_a2)

    # Day 19 - Kai escalating appropriately
    t_k1 = add("dm-U007", "U007", "I found something concerning — there's a memory leak in the decay scheduler. It's slow (~5MB/hour) but over a weekend it could OOM the cluster. Want me to hotfix or wait for the next sprint?", 19, 14)
    add("dm-U007", "U999", "Hotfix. Don't let that sit over the weekend. Tag it as a patch release.", 19, 14, 5, thread_ts=t_k1)
    add("dm-U007", "U007", "On it. PR incoming within the hour.", 19, 14, 8, thread_ts=t_k1)

    # Day 20 - Weekend bot noise
    add("ci-notifications", "U005", "Build #4570 passed. All 857 tests green. Deploy to staging complete.", 20, 4)
    add("ci-notifications", "U005", "Build #4571 passed. All 857 tests green. Deploy to staging complete.", 20, 16)

    # =========================================================================
    # WEEK 4: Autonomy proven, style established, graph deepens
    # =========================================================================

    # Day 20 - Priya load test prep
    add("project-atlas", "U006", "Load test environment is provisioned. Separate cluster so we don't impact staging. Running the soak test overnight.", 20, 10)

    # Day 21 - More bot messages (system should auto-dismiss by now)
    add("ci-notifications", "U005", "Build #4580 passed. All 860 tests green. Deploy to staging complete.", 21, 7)
    add("ci-notifications", "U005", "Build #4581 passed. All 860 tests green. Deploy to staging complete.", 21, 12)
    add("ci-notifications", "U005", "Build #4582 passed. All 860 tests green. Deploy to staging complete.", 21, 18)
    add("ci-notifications", "U005", "Build #4583 passed. All 860 tests green. Deploy to staging complete.", 21, 22)

    # Day 21 - Monday standup Week 4
    add("project-atlas", "U001", "Week 4 standup: load test this week, production deploy next Tuesday. Maya — status on user docs?", 21, 9)
    add("project-atlas", "U002", "User docs 90% complete. Will have final draft by Wednesday for review.", 21, 9, 10)
    add("project-atlas", "U003", "Load test scripts are ready. Starting the 50k concurrent run today.", 21, 9, 15)
    add("project-atlas", "U007", "Contradiction detection design doc is drafted. Sharing for feedback after standup.", 21, 9, 20)

    # Day 21 - Priya UPDATES earlier claim (infra resized)
    add("project-atlas", "U006", "Completed the instance resize. Now running on r6g.2xlarge as planned. Performance improved 3x on graph traversal queries.", 21, 10)

    # Day 21 - Alexis DM check-in
    t_a3 = add("dm-U001", "U001", "How's morale on the team? I know the deadline shift was frustrating for some people.", 21, 16)
    add("dm-U001", "U999", "Team is good. The shift actually relieved pressure. Jordan and Kai are energized. Maya's a bit stretched with the docs + design work simultaneously.", 21, 16, 10, thread_ts=t_a3)
    add("dm-U001", "U001", "Should I talk to Maya? Or do you want to handle it?", 21, 16, 15, thread_ts=t_a3)
    add("dm-U001", "U999", "I'll handle it. She just needs acknowledgment that the docs aren't her only deliverable. I'll chat with her tomorrow.", 21, 16, 20, thread_ts=t_a3)

    # Day 22 - General channel social
    add("general", "U003", "PSA: the coffee machine on 4th floor is broken. 3rd floor still works.", 22, 8)
    add("general", "U007", "Thanks for the heads up. 3rd floor it is.", 22, 8, 5)
    add("general", "U002", "Reminder: Atlas celebration drinks this Friday at 5pm on the rooftop.", 22, 10)

    # Day 22 - User manages Maya (style: supportive)
    t_m1 = add("dm-U002", "U999", "Maya — I know you're juggling the docs and the design work. Want me to take the user docs review off your plate? I can get Jordan to cover it.", 22, 11)
    add("dm-U002", "U002", "That would actually be amazing. I've been stressed about the timeline. Are you sure Jordan has bandwidth?", 22, 11, 10, thread_ts=t_m1)
    add("dm-U002", "U999", "I'll work it out. Focus on the design review. That's where your impact is highest.", 22, 11, 15, thread_ts=t_m1)
    add("dm-U002", "U002", "Thank you 🙏 Really appreciate that.", 22, 11, 20, thread_ts=t_m1)
    # ^ This updates the Day 15 claim about instance types

    # Day 22 - Jordan shares concern (relationship depth)
    t5 = add("dm-U003", "U003", "Between us — I'm a bit worried about the September deadline now that Alexis moved it. She tends to move goalposts. First it was Q3, then August, now September. What if it shifts again?", 22, 16)
    add("dm-U003", "U999", "Valid concern. I think September is real because Dana anchored it externally. But let's build in a 2-week buffer just in case. Don't mention this to Alexis directly — I'll manage the expectation upstream.", 22, 16, 15, thread_ts=t5)
    add("dm-U003", "U003", "Makes sense. Appreciate you handling that. I'll just keep shipping.", 22, 16, 20, thread_ts=t5)

    # Day 22 - More bot noise
    add("ci-notifications", "U005", "Build #4584 passed. All 861 tests green. Deploy to staging complete.", 22, 6)
    add("ci-notifications", "U005", "Build #4585 FAILED. Flaky test in graph_traversal module. Auto-retrying...", 22, 14)
    add("ci-notifications", "U005", "Build #4585 RETRY passed. All 861 tests green. Deploy to staging complete.", 22, 14, 5)

    # Day 23 - Kai has fully earned trust
    add("project-atlas", "U007", "Shipped the entity relationship visualization. Also noticed our test coverage dropped to 87% — I added 15 new tests to bring it back to 91%.", 23, 11)
    add("project-atlas", "U999", "Outstanding initiative Kai. Exactly the kind of ownership we need.", 23, 11, 15)

    # Day 23 - Jordan and user technical sync
    t_j2 = add("dm-U003", "U003", "Load test revealed something interesting: the cache hit rate is 94% for entities with > 5 relationships, but only 62% for leaf nodes. Should we adjust the caching strategy?", 23, 13)
    add("dm-U003", "U999", "Good insight. Leaf nodes are probably new entities that haven't been traversed yet. Let's not over-optimize — 62% is fine for cold entities. Focus on the hot path.", 23, 13, 10, thread_ts=t_j2)
    add("dm-U003", "U003", "Agreed. I'll document the cache behavior for the ops runbook.", 23, 13, 15, thread_ts=t_j2)

    # Day 23 - Sam confirms readiness (consistent, reliable)
    add("dm-U004", "U004", "Just ran our final regression suite against your staging endpoint. 100% pass rate. We're officially production-ready on our side.", 23, 14)
    add("dm-U004", "U999", "Great news. Tuesday deploy is confirmed. I'll send you the production endpoint once it's live.", 23, 14, 10)

    # Day 23 - Dana (rare, high-signal)
    add("dm-U008", "U008", "The board loved the Atlas architecture preview. Specifically called out the belief decay concept. Nice work by your team. Let's schedule a proper demo for the full board in October.", 23, 17)
    add("dm-U008", "U999", "That's great news. I'll coordinate with Alexis on the October demo. The team will be thrilled.", 23, 17, 10)

    # Day 23 - General channel
    add("general", "U006", "New security policy: all production clusters must have encryption at rest enabled by end of month. Atlas is already compliant.", 23, 9)
    add("general", "U001", "Good. We were ahead of this one thanks to Priya's initial setup.", 23, 9, 10)

    # Day 24 - Sam wraps up integration
    add("dm-U004", "U004", "Integration tests are all passing on our end. We're ready for production. Whenever you flip the switch, we're go.", 24, 10)
    add("dm-U004", "U999", "Excellent. I'll coordinate with Priya on the production deployment. Targeting next week.", 24, 10, 15)

    # Day 25 - Maya still waiting (staleness test)
    add("dm-U002", "U002", "Hey, just following up again on the onboarding flow feedback. Design shipped without your input — hope that's okay. If you have thoughts post-ship, still happy to iterate.", 25, 9)

    # Day 24 - Jordan shares good news
    add("project-atlas", "U003", "Load test results are in: 50k concurrent queries, p95 at 145ms, zero errors. We're well within target.", 24, 15)
    add("project-atlas", "U006", "Infra held steady. CPU peaked at 68%, memory at 74%. No scaling needed.", 24, 15, 10)
    add("project-atlas", "U001", "Excellent. We're go for production.", 24, 15, 20)

    # Day 25 - More user style exemplars
    add("engineering-leads", "U999", "Team update: Atlas integration with Sam's API is green. Production deploy next week. Kai's belief decay work got called out by the board — kudos to the whole team. September launch is on track.", 25, 14)
    add("dm-U006", "U999", "Priya — need to schedule the production deploy for Sam's integration. Can you prep the runbook? Targeting Tuesday or Wednesday next week.", 25, 14, 30)
    add("dm-U003", "U999", "Jordan — load test results look great. Nice work on the caching optimization. We're cleared for prod.", 25, 15)
    add("dm-U007", "U999", "Kai — the board noticed the belief decay work. Dana mentioned it specifically. Great contribution.", 25, 15, 30)

    # Day 25 - General channel social
    add("general", "U002", "Celebrating Atlas milestones — drinks Friday at 5? The rooftop bar is open.", 25, 16)
    add("general", "U003", "Absolutely 🍻", 25, 16, 5)
    add("general", "U007", "I'll be there!", 25, 16, 8)
    add("general", "U001", "Wouldn't miss it. First round's on me.", 25, 16, 12)

    # Day 26 - Bot noise continues
    add("ci-notifications", "U005", "Build #4590 passed. All 863 tests green. Deploy to staging complete.", 26, 7)
    add("ci-notifications", "U005", "Build #4591 passed. All 863 tests green. Deploy to staging complete.", 26, 14)
    add("ci-notifications", "U005", "Build #4592 passed. All 863 tests green. Deploy to staging complete.", 26, 20)

    # Day 26 - Kai's trust fully established
    add("project-atlas", "U007", "I've been thinking about post-launch: we should add a 'contradiction detection' module. When two claims about the same entity conflict, surface it for human review instead of silently overwriting.", 26, 11)
    add("project-atlas", "U003", "Love it. That would prevent stale data from corrupting the graph. Want to write a design doc?", 26, 11, 15)
    add("project-atlas", "U007", "Already started one. Will share by EOD.", 26, 11, 20)

    # Day 26 - Maya persistent but lower priority
    add("dm-U002", "U002", "Hi! Just wanted to flag — the entity detail view got shipped without the search enhancement we discussed. If you want, I can add it to the next sprint backlog. No pressure either way.", 26, 13)

    # Day 26 - Priya operational excellence
    add("dm-U006", "U006", "Production runbook is ready. Includes rollback procedures, health checks, and the external API cutover steps. Want to review before Tuesday?", 26, 15)
    add("dm-U006", "U999", "Send it over. I'll review tonight.", 26, 15, 10)

    # Day 27 - Fresh items (will appear in catch-up)
    add("dm-U001", "U001", "Can you prepare the October board demo outline? I need it by Friday. Think: 15 min presentation, focus on the belief graph innovation and business impact.", 27, 9)
    add("dm-U003", "U003", "The graph is at 12k entities now. Query latency holding at p95 < 80ms. Should we start the load test before prod deploy?", 27, 11)
    add("dm-U007", "U007", "Hey, I found a potential issue with the decay algorithm — claims that were recently confirmed are still decaying. I think we need a 'last_confirmed' reset. Want me to fix it or discuss first?", 27, 14)
    add("project-atlas", "U006", "Heads up: getting alerts on the staging Neo4j cluster. Disk usage at 85%. Need to add storage before the load test.", 27, 15)
    add("dm-U002", "U002", "One more thing — the design team wants to do user testing on the graph visualization next week. Can you nominate 3 power users from engineering?", 27, 16)
    add("dm-U004", "U004", "Production keys are provisioned on our end. Ready for the cutover whenever you are. Just need 24h notice.", 27, 16, 30)
    add("dm-U008", "U008", "Thinking about the October board demo — I want to invite two external board observers. Make sure the demo is polished. This could unlock Series C conversations.", 27, 17)

    return messages_by_channel_date


def write_export(output_path: Path, base_date: datetime | None = None):
    """Write a complete Slack export zip."""
    if base_date is None:
        # Default to 4 weeks ago from now
        base_date = datetime.now(UTC) - timedelta(days=28)

    messages = generate_messages(base_date)

    with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zf:
        # users.json
        users_list = [{"id": uid, **info} for uid, info in USERS.items()]
        zf.writestr("users.json", json.dumps(users_list, indent=2))

        # channels.json
        channels_list = [{"id": cid, **info} for cid, info in CHANNELS.items()]
        zf.writestr("channels.json", json.dumps(channels_list, indent=2))

        # Message files: channel_name/date.json
        for channel_name, dates in messages.items():
            # Map DM channels
            if channel_name.startswith("dm-"):
                folder = channel_name
            else:
                folder = channel_name

            for date_str, msgs in dates.items():
                path = f"{folder}/{date_str}.json"
                zf.writestr(path, json.dumps(msgs, indent=2))

    print(f"Generated export: {output_path}")
    print(f"  Users: {len(USERS)}")
    print(f"  Channels: {len(CHANNELS)}")
    msg_count = sum(len(msgs) for dates in messages.values() for msgs in dates.values())
    print(f"  Messages: {msg_count}")
    print(f"  Timespan: {base_date.strftime('%Y-%m-%d')} to {(base_date + timedelta(days=27)).strftime('%Y-%m-%d')}")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Generate synthetic Slack export for demo")
    parser.add_argument("--output", type=Path, default=Path("demo-export.zip"))
    parser.add_argument("--base-date", type=str, default=None, help="Start date YYYY-MM-DD (default: 4 weeks ago)")
    args = parser.parse_args()

    base = None
    if args.base_date:
        base = datetime.fromisoformat(args.base_date).replace(tzinfo=UTC)

    write_export(args.output, base)
