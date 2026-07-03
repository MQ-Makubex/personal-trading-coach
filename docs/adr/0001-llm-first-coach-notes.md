# Use LLM-first coach notes instead of script-generated reports

The stock trading coach will use scripts only to sanitize inputs, parse trade records, build evidence packets, fetch basic market facts, and render Markdown to HTML. The primary coaching artifact is a human-readable Markdown coach note written by the LLM from the evidence packet, position storylines, personal trading modes, and user-provided context, because script-generated reports produced too many generic "无法判断" sections and failed to understand decision continuity across days.
