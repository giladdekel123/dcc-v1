# Evaluation report: baseline-fts-v1

- Date: 2026-09-30  
- Code commit: 09d640f  
- Corpus: 47 documents, 62 revisions, 64 files (register 3717ff517034) - recorded after the run, from eval/frozen/corpus-v1 (the register this run used)  
- Query files: `generated.yaml` (f41998658911), `human.yaml` (5d2f35983b37)

## Summary

| | n | hit@1 | hit@3 | hit@5 | hit@10 | MRR | revision exact/named |
|---|---|---|---|---|---|---|---|
| **overall** | 58 | 0.76 | 0.97 | 0.97 | 1.00 | 0.86 | 11/12 of 15 found (15) |
| generated | 40 | 0.80 | 0.97 | 0.97 | 1.00 | 0.88 | 7/8 of 10 found (10) |
| human | 18 | 0.67 | 0.94 | 0.94 | 1.00 | 0.80 | 4/4 of 5 found (5) |

## By category

| | n | hit@1 | hit@3 | hit@5 | hit@10 | MRR | revision exact/named |
|---|---|---|---|---|---|---|---|
| vague_topic | 9 | 0.56 | 0.89 | 0.89 | 1.00 | 0.72 |  |
| partial_name | 7 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 |  |
| old_revision | 5 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 2/2 of 5 found (5) |
| cross_type | 5 | 0.40 | 1.00 | 1.00 | 1.00 | 0.70 |  |
| date_anchored | 7 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1/1 of 1 found (1) |
| sender_anchored | 6 | 0.67 | 0.83 | 0.83 | 1.00 | 0.77 |  |
| correct_not_latest | 5 | 0.60 | 1.00 | 1.00 | 1.00 | 0.80 | 3/4 of 4 found (4) |
| related_chain | 7 | 0.57 | 1.00 | 1.00 | 1.00 | 0.74 | 2/2 of 2 found (2) |
| status_anchored | 7 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 3/3 of 3 found (3) |

## Per query

| id | category | query | expected | rank | revision |
|---|---|---|---|---|---|
| G001 | vague_topic | the contractor's question about piles hitting soft clay at the east side of the bridge | KVL-CGC-410-RI-S-0012 | 1 |  |
| G002 | vague_topic | problem with the water pipe near the Mill Lane culvert | KVL-CGC-330-RI-S-0013, KVL-NCC-610-LT-U-0014 | 3 |  |
| G003 | vague_topic | pond needs to hold more water because the council cut the discharge rate | KVL-ADM-300-RP-D-0021 | 7 |  |
| G004 | vague_topic | cheaper aggregate for the roundabout road surface | KVL-CGC-510-LT-C-0022, KVL-CGC-510-SB-C-0012 | 1 |  |
| G005 | vague_topic | overnight closures and traffic lights where the new road joins the existing road | KVL-CGC-200-LT-C-0019, KVL-NCC-200-LT-C-0016 | 1 |  |
| G006 | partial_name | piling layout east abutment | KVL-ADM-410-DR-S-0110 | 1 |  |
| G007 | partial_name | drainage layout sheet 2 | KVL-ADM-300-DR-D-0302 | 1 |  |
| G008 | partial_name | variation 07 | KVL-CGC-330-BQ-Q-0007 | 1 |  |
| G009 | partial_name | bill of quantities for the pavements | KVL-ADM-000-BQ-Q-0001 | 1 |  |
| G010 | partial_name | check certificate for the culvert | KVL-BCS-330-CT-S-0002 | 1 |  |
| G011 | partial_name | Pond 1 GA | KVL-ADM-310-DR-D-0310 | 1 |  |
| G012 | old_revision | the first construction issue of the east abutment general arrangement, before the piles were lengthened | KVL-ADM-410-DR-S-0102 | 1 | wanted C01, matched C02 |
| G013 | old_revision | the preliminary drainage strategy from summer 2024 | KVL-ADM-300-RP-D-0014 | 1 | wanted P01, matched P01 (shown) |
| G014 | old_revision | baseline construction programme at contract award | KVL-CGC-100-SC-G-0002 | 1 | wanted P01, matched P01 (shown) |
| G015 | old_revision | Mill Lane culvert drawing issued for construction with the original invert at 10.80 | KVL-ADM-330-DR-S-0205 | 1 | wanted C01, matched C02 |
| G016 | cross_type | the designer's reply to the RFI about soft clay under the piles | KVL-ADM-410-LT-S-0031 | 2 |  |
| G017 | cross_type | minutes of the meeting where the east abutment piling problem was first raised | KVL-CGC-100-MM-G-0007 | 1 |  |
| G018 | cross_type | Northvale Water's reply to the council's trial hole letter | KVL-NVW-610-LT-U-0003 | 2 |  |
| G019 | cross_type | the submittal that followed the contractor's letter about the roundabout surface course aggregate | KVL-CGC-510-SB-C-0012 | 2 |  |
| G020 | date_anchored | progress report for July 2025 | KVL-CGC-100-RP-G-0007 | 1 |  |
| G021 | date_anchored | the monthly progress report issued at the start of September | KVL-CGC-100-RP-G-0008 | 1 |  |
| G022 | date_anchored | progress meeting in mid October 2025 | KVL-CGC-100-MM-G-0012 | 1 |  |
| G023 | date_anchored | the council's letter about the pond from May 2025 | KVL-NCC-320-LT-D-0011 | 1 |  |
| G024 | date_anchored | programme update from October | KVL-CGC-100-SC-G-0002 | 1 | wanted P03, matched P03 (shown) |
| G025 | sender_anchored | letter from Northvale Water accepting the protection slab | KVL-NVW-610-LT-U-0004 | 1 |  |
| G026 | sender_anchored | Arden Moss letter accepting the alternative roundabout surfacing | KVL-ADM-510-LT-C-0036 | 2 |  |
| G027 | sender_anchored | Stratum's ground investigation report | KVL-SGI-410-RP-T-0001 | 1 |  |
| G028 | sender_anchored | letter from Castlegate about lane closures | KVL-CGC-200-LT-C-0019 | 1 |  |
| G029 | correct_not_latest | the east abutment GA drawing we should build from | KVL-ADM-410-DR-S-0102 | 1 | wanted C02, matched P03 (shown) |
| G030 | correct_not_latest | the approved flow control device for Pond 2 | KVL-CGC-320-SB-D-0009 | 1 | wanted P01, matched P01 (shown) |
| G031 | correct_not_latest | the current drainage strategy for the ponds | KVL-ADM-300-RP-D-0021 | 2 |  |
| G032 | related_chain | the drawing that changed after the contractor's question about soft clay | KVL-ADM-410-DR-S-0102, KVL-ADM-410-DR-S-0110 | 3 | wanted C02, matched C02 (shown) |
| G033 | related_chain | the cost variation that came out of the Mill Lane water main clash | KVL-CGC-330-BQ-Q-0007 | 1 |  |
| G034 | related_chain | the report that responded to the council's reduced discharge limit | KVL-ADM-300-RP-D-0021 | 1 |  |
| G035 | related_chain | the follow-up question the contractor asked about the revised piling layout | KVL-CGC-410-RI-S-0015 | 1 |  |
| G036 | status_anchored | the rejected flow control submittal | KVL-CGC-320-SB-D-0009 | 1 | wanted P02, matched P02 (shown) |
| G037 | status_anchored | closed RFI about the bearing plinths | KVL-CGC-410-RI-S-0011 | 1 |  |
| G038 | status_anchored | the surfacing submittal that was approved with comments | KVL-CGC-510-SB-C-0012 | 1 |  |
| G039 | status_anchored | abutment drawing issued for comment in October with a drainage layer | KVL-ADM-410-DR-S-0102 | 1 | wanted P03, matched P03 (shown) |
| G040 | status_anchored | the variation the council accepted for about 48 thousand pounds | KVL-CGC-330-BQ-Q-0007 | 1 |  |
| H001 | partial_name | WBS 330 – culvert clash with existing water main | KVL-CGC-330-RI-S-0013 | 1 |  |
| H002 | vague_topic | WBS 300 drainage. Change in allowable discharge for Pond 2. Pond 2 infrastructure. | KVL-NCC-320-LT-D-0011, KVL-ADM-300-RP-D-0021 | 2 |  |
| H003 | cross_type | WBS 410 River Kest Bridge. Soft clay found below the east abutment piles. RFI and response. | KVL-CGC-410-RI-S-0012, KVL-ADM-410-LT-S-0031 | 1 |  |
| H004 | status_anchored | WBS 510 Eastern Roundabout. Document approving the alternative pavement material for construction. | KVL-ADM-510-LT-C-0036, KVL-CGC-510-SB-C-0012 | 1 |  |
| H005 | vague_topic | WBS 320 Pond 2 East. Somewhere the allowable discharge was changed from 8 to 5 litres per second. | KVL-NCC-320-LT-D-0011 | 2 |  |
| H006 | sender_anchored | WBS 330 Mill Lane Culvert. Document from Northvale Water about protecting the existing water main. | KVL-NVW-610-LT-U-0004, KVL-NVW-610-LT-U-0003 | 7 |  |
| H007 | date_anchored | WBS 100 Project Management. Meeting minutes from around July or August where the recovery programme was discussed. | KVL-CGC-100-MM-G-0010, KVL-CGC-100-MM-G-0008 | 1 |  |
| H008 | old_revision | WBS 410 River Kest Bridge. I need the earlier general arrangement drawing, before the construction revision. | KVL-ADM-410-DR-S-0102 | 1 | wanted P02, matched C02 |
| H009 | status_anchored | WBS 320 Pond 2 East. Flow-control submittal that was rejected. | KVL-CGC-320-SB-D-0009 | 1 | wanted P02, matched P02 (shown) |
| H010 | related_chain | WBS 410 River Kest Bridge. Drawing issued after the RFI about the soft clay below the piles was resolved. | KVL-ADM-410-DR-S-0102, KVL-ADM-410-DR-S-0110 | 1 | wanted C02, matched C02 (shown) |
| H011 | sender_anchored | WBS 510 Eastern Roundabout. I think there was a letter from the contractor about changing the asphalt aggregate to PSV 60 or 65. | KVL-CGC-510-LT-C-0022 | 1 |  |
| H012 | related_chain | WBS 320 Pond 2 East. What document caused us to enlarge Pond 2? | KVL-NCC-320-LT-D-0011 | 3 |  |
| H013 | correct_not_latest | WBS 320 Pond 2 East. I need the drawing that was approved for the flow control arrangement. | KVL-CGC-320-SB-D-0009 | 2 | wanted P01, matched P01 (shown) |
| H014 | date_anchored | WBS 330 Mill Lane Culvert. Something from around the time of the trial hole about the water main being deeper than expected. | KVL-NCC-610-LT-U-0014, KVL-CGC-100-MM-G-0007 | 1 |  |
| H015 | correct_not_latest | WBS 410 River Kest Bridge. Which general arrangement drawing were we supposed to use for construction? | KVL-ADM-410-DR-S-0102 | 1 | wanted C02, matched C02 (shown) |
| H016 | vague_topic | WBS 330 Mill Lane Culvert. What was the cost of the variation for protecting the water main? | KVL-CGC-330-BQ-Q-0007 | 1 |  |
| H017 | related_chain | WBS 300 Drainage. What replaced the earlier drainage strategy report? | KVL-ADM-300-RP-D-0021 | 2 |  |
| H018 | vague_topic | WBS 510 Eastern Roundabout. Where's the document where we finally agreed what surfacing to use? | KVL-ADM-510-LT-C-0036, KVL-CGC-510-SB-C-0012 | 1 |  |

## Not in the top 3

- **G003** (vague_topic): "pond needs to hold more water because the council cut the discharge rate" - rank 7; top 3 were KVL-NCC-320-LT-D-0011, KVL-ADM-320-DR-D-0320, KVL-ADM-300-RP-D-0014
- **H006** (sender_anchored): "WBS 330 Mill Lane Culvert. Document from Northvale Water about protecting the existing water main." - rank 7; top 3 were KVL-CGC-330-BQ-Q-0007, KVL-CGC-330-RI-S-0013, KVL-ADM-330-DR-S-0206
