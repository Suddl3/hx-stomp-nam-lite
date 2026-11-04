"""Pack the NAM kernel's on-chip pieces (far_d 17, 2 slots) into the Floor's freed static regions
(13-block layout) by first-fit decreasing; rings go in each instance's placeholder memory."""
regions = {"R3 Block0 (heap a tail)": 0xeb8, "R1 Block3 (free tail)": 0xd66, "R2 Block3 (heap b tail)": 0x6d8}
items = {"hot code": 1635, "cold code": 294, "stream A": 2015, "stream B": 2015, "heads A": 102, "heads B": 102,
         "X": 48, "IN": 16, "WBUF": 156,
         'SAVE': 64, 'SLOTTAB': 2, 'HS': 48, 'SB': 576, 'OUTBUF': 576, 'RCH0': 96, 'RCH1': 96, 'WCH0': 78,
         'WCH1': 78, 'WCH2': 78, 'LCH': 12, 'JOBS': 120, 'TABLE': 391, 'FARTAB': 12, 'WADDR': 12, 'CLR': 108,
         'DRIVE_TAB': 101, 'FADE_TAB': 18, 'flags/report (B3..REP+16)': 0}
pin = {"hot code": "R2 Block3 (heap b tail)", "stream A": "R3 Block0 (heap a tail)", "stream B": "R1 Block3 (free tail)"}
free = dict(regions); place = {}
for k, r in pin.items():
    free[r] -= items[k]; place[k] = r
for k, v in sorted(items.items(), key=lambda x: -x[1]):
    if k in place or not v: continue
    r = next((r for r in free if free[r] >= v), None)
    if r is None: raise SystemExit(f"does not fit: {k} {v}, free {free}")
    free[r] -= v; place[k] = r
need = sum(items.values()); have = sum(regions.values())
print(f"static need {need} of {have}, spare {have - need}")
for r in regions:
    print(f"{r}: {regions[r]} words, spare {free[r]}: " + ", ".join(k for k in place if place[k] == r))
dm, pm = 0x596 - 145, 0x1fa - 13
rings = {14: 96, 15: 600, "group 0-2": 336, "group 7-9": 336, "group 16-18": 336}
print(f"per instance (amp placeholder): DM {dm} <- layer 15 + groups 0-2, 7-9 = {600 + 672}; "
      f"PM {pm} <- group 16-18 + layer 14 = {336 + 96}")
