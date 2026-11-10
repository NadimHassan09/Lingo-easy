from qa.mkpatch import mk
P = [
("RE006-Q03", {"B": "Their clothes and personal belongings", "C": "Their holidays and weekend plans"}),
("RE006-Q04", {"A": "Flatmates cook meals for each other", "B": "Flatmates often pay part of your rent"}),
("RE006-Q05", {"A": "They had never argued with a flatmate", "C": "They had moved out because of noise"}),
("RE006-Q13", {"A": "Avoid sharing a flat with your friends", "C": "Choose the cheapest flat you can find"}),
("RE007-Q02", {"A": "Cells that attack germs in the blood", "C": "Proteins made by the body's own cells"}),
("RE007-Q03", {"A": "They carry oxygen to the infected tissue", "B": "They make the body ill for several days"}),
("RE007-Q04", {"A": "The germ is stronger the first time it enters", "B": "Antibodies are harmful when they first appear"}),
("RE007-Q05", {"A": "They kill every germ in the body at once", "B": "They prevent all side effects of vaccines"}),
("RE008-Q02", {"A": "Because of noise from the airport", "C": "Because of new museums for visitors"}),
("RE008-Q03", {"B": "The building of new hotels", "C": "Cheaper flights for tourists"}),
("RE008-Q04", {"B": "Tourists rarely spend money in local shops", "C": "Local people refuse to work in tourism"}),
("RE008-Q05", {"B": "It has doubled since the year 1951", "C": "It has stayed the same since then"}),
("RE009-Q01", {"C": "By around fifty per cent"}),
("RE009-Q03", {"A": "It doubled over the same period", "C": "It stayed the same as before"}),
("RE009-Q04", {"A": "They are the largest source of plastic waste", "B": "They are recycled more easily than most"}),
("RE009-Q05", {"A": "It has no lasting effect on behaviour", "C": "It makes shopping harder for families"}),
("RE010-Q01", {"A": "News services for political parties", "C": "Political campaigns for new voters"}),
("RE010-Q03", {"A": "The company had not studied the effects", "C": "The platform was losing users every year"}),
("RE010-Q04", {"A": "Parents do not understand the law on age limits", "C": "Platforms ignore emails sent by worried parents"}),
("RE010-Q05", {"A": "They are strictly enforced by the platforms", "B": "They are set too low for most teenagers"}),
]
mk("patch_011_placement_b", P)
