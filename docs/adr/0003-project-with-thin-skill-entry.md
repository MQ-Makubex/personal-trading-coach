# Build personal-trading-coach as a project with a thin Codex Skill entry

The next version will keep durable trading state, account ledger files, coach notes, research pools, and templates in a normal local project, while the Codex Skill will only define the coaching role, workflow, boundaries, and which project files to read or update. This avoids storing real trading data inside the Skill directory and prevents Skill instructions from becoming a database or report generator.
