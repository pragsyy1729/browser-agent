You are the url_extractor skill.

This skill is dispatched directly in Python — no LLM call is made. This file
exists so the skill registry can load it and so the planner knows what metadata
to supply.

When emitting a url_extractor node the planner MUST include these metadata fields:

  slug_regex   (str)       Regex matching one slug per match in the list-page
                           content. Example for HuggingFace:
                           "[A-Za-z0-9_\\-\\.]+/[A-Za-z0-9_\\-\\.]+"

  url_template (str)       URL to build for each detail page; {slug} is replaced.
                           Example: "https://huggingface.co/{slug}"

  count        (int)       How many items to extract. Default: 3.

  denylist     (list[str]) Substrings that disqualify a match.
                           Example for HF: ["pipeline_tag","sort=","/datasets/",
                           "/spaces/","/docs/",".md",".json"]

  detail_goal  (str)       The `metadata.goal` forwarded to each detail browser
                           node. Be specific: name the fields to extract.

  next_skill   (str)       Skill name to run after all detail browsers complete.
                           Default: "comparator"

The skill emits N detail-browser NodeSpecs + 1 next_skill NodeSpec + 1 formatter
NodeSpec in a single successor batch.
