import io
import unittest
from unittest.mock import patch

from PIL import Image
from screenshot_ocr import extract_candidates, recognize_screenshot, validate_review


class ScreenshotTests(unittest.TestCase):
    def test_purity_is_extracted(self):
        stats, types = extract_candidates("Purity: 75\nThis Augmentation fits in slot types: 14")
        self.assertEqual(stats["purity"], 75)
        self.assertEqual(types, [14])

    def test_user_actual_purity_ocr_output(self):
        text = (
            "<—o i AR IGG UC Ola Description [ Lore Extra Planar Potential Shard "
            "No Trade, Altunable, Augmentation, Infusible, Prestige "
            "Head Arms Wrist Range Hands Primary Secondary Chest Legs Feet "
            "Size: TINY  Purily: 35 Tribute: 1200 Req Level: 105 "
            "© Unmodified Extra Planar Potential Shard e "
            "This Augmentation fits in slot types: 13 (Energeiac: Group), 14 (Energeiac: Raid) "
            "Restictions - Armor Only This augment can only safely be removed with the Perfected "
            "Augmentation Distiller."
        )
        stats, types = extract_candidates(text)
        self.assertEqual(stats["purity"], 35)
        self.assertEqual(stats["size"], "TINY")
        self.assertEqual(stats["tribute"], 1200)
        self.assertEqual(stats["required_level"], 105)
        self.assertEqual(types, [13, 14])
        self.assertNotIn("purily", stats)

    def test_purity_ocr_misread_requires_a_number_and_full_label(self):
        self.assertEqual(extract_candidates("Purily: unclear")[0], {})
        self.assertEqual(extract_candidates("Impurily: 35")[0], {})
        self.assertEqual(extract_candidates("PURILY: 0")[0], {"purity": 0})

    def test_tourmaline_item_window_transcription(self):
        text = """Tourmaline of Alteration
Description
Tourmaline of Alteration
Lore, No Trade, Augmentation, Prestige
Ear Head Face Neck Shoulders Arms Back Wrist
Range Hands Primary Secondary Fingers Chest Legs
Feet Waist
Size: TINY
Tribute: 2000
Req Level: 125
Mana Regen: 11
Heal Amount 30
Spell Dmg: 30
Clairvoyance: 30
Skill Mod: Specialize Alteration 15 % +5 (45 Max)
This Augmentation fits in slot types: 3 (General: Spell Effect)
"""
        # Some OCR output omits the colon shown in the inspection window.
        stats, types = extract_candidates(text)
        self.assertEqual(types, [3])
        self.assertEqual(stats, {
            "size": "TINY", "tribute": 2000, "required_level": 125,
            "mana_regen": 11, "heal_amount": 30, "spell_damage": 30, "clairvoyance": 30,
            "skill_mod": "Specialize Alteration 15 % +5 (45 Max)",
            "item_flags": "Lore, No Trade, Augmentation, Prestige",
            "equip_slots": "Ear Head Face Neck Shoulders Arms Back Wrist Range Hands Primary "
                           "Secondary Fingers Chest Legs Feet Waist",
        })

    def test_do_not_mix_item_socket_types_with_augment_types(self):
        text = ("Slot 1, Type 3 (General: Spell Effect)\nSlot 2, Type 5\n"
                "Slot 3, Type 8\nAC: 505\n")
        stats, types = extract_candidates(text)
        self.assertEqual(stats, {"ac": 505, "socket_1_type": 3, "socket_2_type": 5, "socket_3_type": 8})
        self.assertEqual(types, [])

    def test_extract_equipment_sockets_from_green_pulse_ocr(self):
        text = ("Green Pulse\nSlot 1, type 3 (General: Spell Effect): Stone of Judgment\n"
                "sag| Slot2, type 5 (General: Multiple Slot):\n"
                "#3 Slot, type 8 (General: Raid):\n")
        self.assertEqual(extract_candidates(text), (
            {"socket_1_type": 3, "socket_2_type": 5, "socket_3_type": 8}, []
        ))

    def test_socket_detection_does_not_guess_missing_or_conflicting_slots(self):
        text = "Slot, type 8\nSlot 1, type 3\nSlot 1, type 5\nSlot 0, type 8\nSlot 2, type 256"
        self.assertEqual(extract_candidates(text), ({}, []))

    def test_extract_compatible_slot_types_with_labels(self):
        examples = [
            ("This Augmentation fits in slot types: 5 (General: Multiple Slot)", [5]),
            ("This Augmentation fits in slot types: 7 (General: Group), 8 (General: Raid)", [7, 8]),
            ("This Augmentation fits in slot types: 7 (General: Group),\n8 (General: Raid)", [7, 8]),
            ("This Augmentation fits in slot types: 8 (Tier 2), 7 (General), 8 (Raid)", [7, 8]),
            ("Augmentation type: 7 8\nAC: 42", [7, 8]),
        ]
        for text, expected in examples:
            with self.subTest(text=text):
                self.assertEqual(extract_candidates(text)[1], expected)
        self.assertEqual(extract_candidates(
            "This Augmentation fits in slot types: 5 (General)\nSlot 1, Type 8\nAC: 42"
        )[1], [5])

    def test_user_actual_tourmaline_ocr_output(self):
        text = ("<o orrmaiine of Aiteraton EK) Description as Tourmaline of Alteration "
                "Lore, No Trade, Augmentation, Prestige R Ear Head Face Neck Shoulders Arms Back Wrist "
                "Range Hands Primary Secondary Fingers Chest Legs Feet Waist Size: TINY Tribute: 2000 "
                "Req Level: 125 Mana Regen: 11 Heal Amount 30 Spell Dmg: 30 Clairvoyance: 30 "
                "© Unmodified Tourmaline of Alteration e Skill Mod: Specialize Alteration 15 % +5 (45 Max) "
                "This Augmentation fits in slot types: 3 (General: Spell Effect) "
                "You mustuse a solvent Class XXI Augmentation Distiller or higher, or use a Perfected "
                "Augmentation Distiller, to remove this augment safely.")
        stats, types = extract_candidates(text)
        self.assertEqual(types, [3])
        self.assertEqual(stats, {
            "size": "TINY", "tribute": 2000, "required_level": 125,
            "mana_regen": 11, "heal_amount": 30, "spell_damage": 30, "clairvoyance": 30,
            "skill_mod": "Specialize Alteration 15 % +5 (45 Max)",
            "item_flags": "Lore, No Trade, Augmentation, Prestige",
            "equip_slots": "Ear Head Face Neck Shoulders Arms Back Wrist Range Hands Primary "
                           "Secondary Fingers Chest Legs Feet Waist",
            "distiller_class": "XXI",
        })

    def test_extract_stats_and_types_without_inventing_values(self):
        stats, types = extract_candidates(
            "Augmentation type: 7 8\nAC: 113\nSTR: +22+16 HP: +1,600 MANA: +1600 ENDUR: +1600"
        )
        self.assertEqual(types, [7, 8])
        self.assertEqual(stats, {"ac": 113, "str": 22, "heroic_str": 16, "hp": 1600, "mana": 1600, "endurance": 1600})
        self.assertEqual(extract_candidates("Slot 1, Type 8\nAC: unclear"), ({"socket_1_type": 8}, []))

    def test_green_pulse_full_visible_stat_transcription(self):
        text = """Green Pulse
Size: SMALL AC: 758
Weight: 1.1 HP: 21785
Tribute: 66483 Mana: 21726
Rec Level: 130 End: 21726
Req Level: 130
Strength: 64 +89 Magic: 108 Attack: 151
Stamina: 88 +163 Fire: 93 HP Regen: 30
Intelligence: 81 +186 Cold: 119 Mana Regen: 33
Wisdom: 95 +111 Disease: 119 End Regen: 1
Agility: 112 +98 Poison: 101 Heal Amount 246
Dexterity: 88 +131 Corrupt: 2 Spell Dmg: 246
Charisma: 88 +173 Clairvoyance: 310
Slot 1, type 3 (General: Spell Effect)
Slot 2, type 5 (General: Multiple Slot)
Slot 3, type 8 (General: Raid)
Skill Mod: Dodge 10 % (45 Max)
"""
        stats, types = extract_candidates(text)
        self.assertEqual(types, [])
        self.assertEqual(stats, {
            "size": "SMALL", "ac": 758, "weight": "1.1", "hp": 21785,
            "tribute": 66483, "mana": 21726, "endurance": 21726,
            "recommended_level": 130, "required_level": 130,
            "str": 64, "heroic_str": 89, "sta": 88, "heroic_sta": 163,
            "int": 81, "heroic_int": 186, "wis": 95, "heroic_wis": 111,
            "agi": 112, "heroic_agi": 98, "dex": 88, "heroic_dex": 131,
            "cha": 88, "heroic_cha": 173,
            "magic": 108, "fire": 93, "cold": 119, "disease": 119,
            "poison": 101, "corruption": 2, "attack": 151, "hp_regen": 30,
            "mana_regen": 33, "endurance_regen": 1, "heal_amount": 246,
            "spell_damage": 246, "clairvoyance": 310,
            "socket_1_type": 3, "socket_2_type": 5, "socket_3_type": 8,
            "skill_mod": "Dodge 10 % (45 Max)",
        })

    def test_base_heroic_values_and_unknown_components(self):
        stats, _ = extract_candidates(
            "STR: +22+16 STA: -5 +3 AGI: 0+0 DEX: 12 WIS: +7 "
            "INT: 1,200 + 34 CHA: 9 + Magic: 3+2\n"
            "Endurance Regen: 4 Endurance: 100"
        )
        self.assertEqual(stats, {
            "str": 22, "heroic_str": 16, "sta": -5, "heroic_sta": 3,
            "agi": 0, "heroic_agi": 0, "dex": 12, "wis": 7,
            "int": 1200, "heroic_int": 34, "cha": 9,
            "magic": 3, "heroic_magic": 2, "endurance_regen": 4, "endurance": 100,
        })

    def test_distiller_class_extraction_requires_complete_classed_distiller(self):
        examples = [
            "You mustuse a solvent Class XXI Augmentation Distiller"
            "You mustuse a solvent Class XXI Augmentation Distiller",
            "You must use a solvent Class XXI\nAugmentation Distiller or higher, "
            "or use a Perfected Augmentation Distiller.",
            "solvent class xxi augmentation distiller",
        ]
        for text in examples:
            with self.subTest(text=text):
                self.assertEqual(extract_candidates(text), ({"distiller_class": "XXI"}, []))
        for text in ("Perfected Augmentation Distiller", "solvent Class Augmentation Distiller",
                     "Class XXI Augmentation Distiller"):
            with self.subTest(text=text):
                self.assertEqual(extract_candidates(text), ({}, []))

    def test_distiller_classes_require_review_for_invalid_ocr_and_perfected_only(self):
        for numeral in ("I", "II", "IV", "IX", "X", "XII", "XIX", "XXI", "XXIX", "XXX"):
            text = f"You must use a solvent Class {numeral} Augmentation Distiller or higher."
            stats, _ = extract_candidates(text)
            self.assertEqual(stats["distiller_class"], numeral)
            validate_review('{"distiller_class":"' + numeral + '"}', "", text)
        text = "You must use a solvent Class XIL Augmentation Distiller or higher."
        stats, _ = extract_candidates(text)
        self.assertEqual(stats["distiller_class"], "XIL")
        for numeral in ("XIL", "XXXX", "IIII", "ABC", "31"):
            with self.subTest(numeral=numeral), self.assertRaisesRegex(ValueError, "Roman numeral"):
                validate_review('{"distiller_class":"' + numeral + '"}', "", text)
        text = "You must use a Perfected Augmentation Distiller to remove this augment."
        stats, _ = extract_candidates(text)
        self.assertEqual(stats["distiller_class"], "Perfected only")
        validate_review('{"distiller_class":"Perfected only"}', "", text)
        ambiguous = ("You must use a solvent Class XIL Augmentation Distiller or higher, "
                     "or use a Perfected Augmentation Distiller.")
        self.assertEqual(extract_candidates(ambiguous)[0]["distiller_class"], "XIL")
        self.assertNotIn("distiller_class", extract_candidates(
            "You must use a solvent Class ??? Augmentation Distiller or higher, "
            "or use a Perfected Augmentation Distiller.")[0])

    def test_review_rejects_bad_values(self):
        for stats, types, raw in [('[]', '7', 'x'), ('{"ac":"42"}', '7', 'x'),
                                  ('{"ac":42}', '256', 'x'), ('{}', '', 'x'),
                                  ('{"ac":42}', '7', ''), ('{"socket_1_type":"8"}', '', 'x'),
                                  ('{"socket_1_type":0}', '', 'x'), ('{"socket_2_type":256}', '', 'x')]:
            with self.subTest(stats=stats, types=types, raw=raw), self.assertRaises(ValueError):
                validate_review(stats, types, raw)
        stats, types = validate_review('{"ac":0,"str":"+3+4"}', '8|7|8', 'confirmed text')
        self.assertEqual(stats["ac"], 0)
        self.assertEqual(stats["ocr_text"], "confirmed text")
        self.assertEqual(types, [7, 8])

    def test_invalid_images_and_missing_ocr_are_explicit(self):
        with self.assertRaises(ValueError):
            recognize_screenshot(b"not an image")
        image = io.BytesIO()
        Image.new("RGB", (20, 20), "white").save(image, format="PNG")
        with patch("screenshot_ocr.subprocess.run", side_effect=FileNotFoundError):
            with self.assertRaisesRegex(RuntimeError, "not installed"):
                recognize_screenshot(image.getvalue())
