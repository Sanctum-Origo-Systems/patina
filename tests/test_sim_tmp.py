from difflib import SequenceMatcher
s = lambda a, b: SequenceMatcher(None, a.lower(), b.lower()).ratio()
d = "Sure, I will review it today!"
print("acted", round(s(d, d), 3))
print("edited", round(s(d, "No need, I already handled the review myself earlier"), 3))
print("unrelated", round(s(d, "Completely unrelated topic about lunch plans"), 3))
