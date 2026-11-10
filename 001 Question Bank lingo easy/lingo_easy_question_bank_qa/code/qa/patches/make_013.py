from qa.mkpatch import mk
P = [
("LI607-Q01", {"C": "Governments pay for every planning decision made"}),
("RE605-Q05", {"A": "Cheaper electricity for factory owners everywhere"}),
("LI008-Q05", {"B": "She sent an email to the whole student body"}),
("LI009-Q09", {"A": "Volunteering costs organisations very little to run each year"}),
("RE006-Q13", {"A": "Avoid sharing a flat with your close friends", "C": "Choose the cheapest flat that you can find"}),
]
mk("patch_013_third_pass", P, "third pass: removes 'all of' phrasing that the extreme-wording check flags; key unchanged")
