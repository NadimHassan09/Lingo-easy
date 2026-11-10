from qa.mkpatch import mk
P = [
("RE408-Q03", {"A": "The colours fade after a few washes", "B": "Large amounts of water are wasted"}),
("RE408-Q04", {"A": "Recycling clothes is against the law", "B": "People refuse to donate worn clothes"}),
("RE408-Q05", {"B": "Charities refuse to accept used clothes", "C": "The clothes are burned before they arrive"}),
("RE409-Q03", {"B": "To bring peace between Greek cities", "C": "To choose which athletes could compete"}),
("RE409-Q04", {"A": "Anyone who could pay the entry fee", "B": "Both men and women of any class"}),
("RE409-Q05", {"A": "A gold medal and a purse", "C": "A bronze statue of Zeus"}),
("RE410-Q01", {"A": "Predict where accidents will happen", "B": "Charge drivers for waiting at junctions"}),
("RE410-Q02", {"A": "Crime fell by about a third overall", "C": "Costs doubled while energy use stayed the same"}),
("RE410-Q04", {"A": "The company ran out of funding in 2020", "B": "The technology failed in early tests"}),
("RE410-Q05", {"B": "They have to pay much higher taxes", "C": "They must move to another district"}),
]
mk("patch_005_B2b", P)
