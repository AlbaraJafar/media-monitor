# Gold-set labeling guide

The gold set defines what "correct" means for this system, so the rules live
here — not in anyone's head. Labels were drafted by an AI assistant following
this guide *without seeing the pipeline's predictions*, then every row was
reviewed by a human analyst (see `reviewed_by` / `changed` columns in
`gold_review.csv`). Report the number of changed rows alongside the metrics.

## Who the reader is

The communications directorate of a Saudi tourism entity. The on-call analyst
is paged for high-risk items and must be able to act on them; the Director
General reads the daily briefing.

## `relevant`

`true` if the article bears on Saudi tourism, travel to/within the Kingdom,
destinations and giga-projects, aviation/visa/entry, visitor-facing events, or
the reputation of the Kingdom *as a destination*. `false` for Saudi news with
no tourism angle (domestic politics, military operations, oil markets, crime,
sport results without a visitor angle) and for non-Saudi news.

Borderline rule: if a tourism communications officer would plausibly want the
item in the daily briefing, it is relevant.

## `themes` (multi-label, empty iff not relevant)

- `national_tourism_strategy_and_visitor_numbers` — strategy, targets, visitor/
  spend statistics, occupancy, rankings, domestic tourism campaigns, licensing
  and regulation of the tourism sector.
- `destination_and_giga_project_launches` — NEOM, Red Sea, Qiddiya, Diriyah,
  AlUla etc.; openings, milestones, delays, new attractions and events venues.
- `aviation_visa_and_entry_policy` — visas, entry rules, airlines, routes,
  airports, airspace and flight disruption.
- `reputational_risk_or_negative_coverage` — coverage that could damage the
  entity's or the Kingdom's image *as a destination*: visitor safety, incidents
  involving tourists, travel advisories, mistreatment/scam allegations,
  environmental or human-rights criticism of tourism projects, viral complaints.
  Neutral announcements are NOT this theme just because they could go wrong.

## `sentiment`

Tone toward the entity / Saudi tourism, not the tone of the world: a neutral
wire report of a delay is `neutral`; criticism is `negative`.

## `is_high_risk` — the alert policy

`true` only if the on-call **tourism** analyst should be paged within 15
minutes: a credible, current story that bears on visitors, destinations,
flagship projects or the entity, and that a spokesperson may need to answer
today. Examples: travel advisories against visiting, tourists harmed or
mistreated, flight disruption caused by security events, viral allegations,
prominent criticism of a flagship project.

`false` for geopolitical/military, judicial or economic stories without a
visitor angle — even severe ones. They are owned by other government
communications teams; paging the tourism analyst for them causes alert
fatigue, which is how the one alert that matters gets ignored. Such items can
still be `relevant` with moderate risk and appear in the briefing.

## `priority`

`high` = belongs at the top of today's briefing; `medium` = worth a line;
`low` = background.
