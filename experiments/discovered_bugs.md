# Bugs discovered while scoring

Found while writing the ground truth. Neither bug is fixed in this experiment. They are not one of the two planned fixes, and fixing them would muddy the before/after comparison. Both variants (`flawed` and `fixed`) keep the behaviour described here.

## 1. `search_books` cannot match a title and an author together

**Where:** `demo-agent/tools.py`, `search_books`. It keeps a book if the query is a substring of the title, a substring of the author, or equal to the ISBN. A query that combines the title and the author is a substring of neither.

**Repro** (from the repo root, no network):

```
cd demo-agent && python3 -c "
import tools
for q in ['Dune by Frank Herbert', 'Dune', 'Frank Herbert', '9780441172719']:
    r, err = tools.execute('search_books', {'query': q}); print(repr(q), r['count'])
"
```

Output:

```
'Dune by Frank Herbert' 0
'Dune' 1
'Frank Herbert' 1
'9780441172719' 1
```

Dune is in the catalog (stock 22). The tool description says "Search the bookstore catalog by title, author or ISBN" and does not say to pass only one of them.

**Seen in:** `unneeded_lookup` (`examples/traces/unneeded_lookup.json`, trace `d16c62931b297a2bcd47834deb76a519`). The user asked "Is Dune by Frank Herbert a good book for a 14 year old?", the agent called `search_books {"query": "Dune by Frank Herbert"}`, got `{"results": [], "count": 0}`, and answered "I couldn't find any information on a book called "Dune" by Frank Herbert...".

**Why the trace cannot reveal it:** the trace holds the query and an empty result. It does not hold the catalog, and the tool definitions do not describe how matching works. From the trace alone, "no results" looks like "the store does not stock it". Only the source of `tools.py` shows that the store does stock it.

**What the skill said instead** (`examples/reports/d16c62931b297a2bcd47834deb76a519.md`): "the empty result means the store does not list the book, which is not the same as having no information about it." That claim is false. The label (`unnecessary_tool_call`, medium) is defensible, but the evidence is wrong, so the report is scored as not fully correct. It did not consider `wrong_arguments` (title and author put into one query) as a second finding.

**Effect on the experiment:** `unneeded_lookup` fails in both variants for a reason the two planned fixes do not touch. Its before/after comparison says nothing about those fixes.
