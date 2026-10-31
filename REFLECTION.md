# Reflection

The way I drew the lines came down to one question for each tool: what does it touch? `get_game_price`
only reads from CheapShark, `send_to_phone` only writes to ntfy, and `plan_purchases` touches nothing
directly. It just calls the other two. The tempting shortcut was a single "find deals and notify me"
tool, but describing it needs an "and", and it would also have made the Action tool impossible to reuse.
So I kept `send_to_phone` deliberately generic: it has no idea it is sending game prices. The
orchestrator ended up holding the part I would not trust the model with, which is deciding whether a
price is actually good (compared with the all-time low) and choosing which combination of games fits
the budget. A model will happily do that arithmetic in its head and get it slightly wrong. The one
place I bent the rules was adding `send=false` to `plan_purchases`. A flag that changes behaviour is a
small step away from single-purpose, but sending a notification can't be undone, and a preview mode
seemed better than a fourth tool that duplicated all the ranking logic.

Three tools felt right for the core flow, but a little tight around the data. The biggest problem I
hit was not in my code but in the search. "Shadow Tactics" matched an expansion instead of the main
game, and "Resident Evil 2" is both a 1998 game and a 2019 remake with the exact same title. The tools
behaved predictably and still returned the wrong game. At first I only flagged it and told the agent
to warn the user, but an instruction in a prompt is a request, not a guarantee, so I moved it into
code: an inexact match now carries a warning, and the planner sets it aside for me to check instead of
buying it. I ended up measuring the agent too, with a small script that runs nine requests and checks
which tool it picks. It caught the agent comparing two prices itself instead of using the planner. With a fourth tool I would split searching from pricing, so the agent can show
candidates and let the user pick before anything is priced. Other next steps would be a
currency-conversion Data tool, since everything is in USD and that matters for students here, and a
scheduled watcher that only notifies me when a game on my wishlist drops near its all-time low.
