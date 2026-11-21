import unittest

from app import simulator as sim

CHEM_ALL = ["hcl", "h2so4", "naoh", "na2co3", "cuso4", "nacl", "agno3", "bacl2", "zn", "phph", "mo", "h2o"]
PHYS_ALL = ["battery", "resistor", "bulb", "ammeter", "voltmeter", "switch"]


def run(subject, steps, allowed):
    """Применяет действия подряд; возвращает (состояние, события последнего шага, вся оценка)."""
    state = sim.empty_state(subject)
    prev = sim.evaluate(subject, state)
    events, cur = [], prev
    for step in steps:
        if isinstance(step, str):
            step = ("add", step, None)
        action, item, index = step
        state, err = sim.apply_action(subject, state, action, item, index, allowed)
        assert err is None, err
        cur = sim.evaluate(subject, state)
        events = sim.new_events(subject, prev, cur)
        prev = cur
    return state, events, cur


class ChemistryTests(unittest.TestCase):
    def test_empty_flask(self):
        ev = sim.evaluate("chemistry", sim.empty_state("chemistry"))
        self.assertIsNone(ev["view"]["ph"])
        self.assertEqual(ev["obs"], set())

    def test_ph_of_single_reagents(self):
        _, _, ev = run("chemistry", ["hcl"], CHEM_ALL)
        self.assertEqual(ev["view"]["ph"], 1.0)
        _, _, ev = run("chemistry", ["naoh"], CHEM_ALL)
        self.assertEqual(ev["view"]["ph"], 13.0)
        _, _, ev = run("chemistry", ["h2o"], CHEM_ALL)
        self.assertEqual(ev["view"]["ph"], 7.0)
        _, _, ev = run("chemistry", ["hcl", "h2o"], CHEM_ALL)
        self.assertEqual(ev["view"]["ph"], 1.3)

    def test_neutralization_with_phenolphthalein(self):
        _, events, ev = run("chemistry", ["phph", "naoh"], CHEM_ALL)
        self.assertIn("ind_phph_pink", events)
        self.assertEqual(ev["view"]["liquid"], "#d6336c")
        _, events, ev = run("chemistry", ["phph", "naoh", "hcl"], CHEM_ALL)
        self.assertIn("neutralization", events)
        self.assertIn("ind_discolor", events)
        self.assertTrue(ev["view"]["heat"])
        self.assertEqual(ev["view"]["ph"], 7.0)
        self.assertEqual(ev["view"]["liquid"], sim.BASE_LIQUID)

    def test_methyl_orange(self):
        _, events, _ = run("chemistry", ["mo", "hcl"], CHEM_ALL)
        self.assertIn("ind_mo_red", events)
        _, events, _ = run("chemistry", ["mo", "naoh"], CHEM_ALL)
        self.assertIn("ind_mo_yellow", events)

    def test_copper_hydroxide_precipitate(self):
        _, events, ev = run("chemistry", ["cuso4", "naoh", "naoh"], CHEM_ALL)
        self.assertIn("ppt_cu_oh_2", ev["obs"])
        self.assertEqual(ev["view"]["solids"][0]["color"], sim.PRECIP_COLOR["ppt_cu_oh_2"])
        self.assertEqual(ev["view"]["ph"], 7.0)

    def test_acid_blocks_copper_hydroxide(self):
        _, _, ev = run("chemistry", ["cuso4", "hcl", "naoh"], CHEM_ALL)
        self.assertNotIn("ppt_cu_oh_2", ev["obs"])  # щёлочь ушла на нейтрализацию

    def test_silver_chloride(self):
        _, events, _ = run("chemistry", ["agno3", "nacl"], CHEM_ALL)
        self.assertEqual(events, ["ppt_agcl"])
        _, events, _ = run("chemistry", ["agno3", "hcl"], CHEM_ALL)
        self.assertEqual(events, ["ppt_agcl"])

    def test_barium_sulfate(self):
        _, events, _ = run("chemistry", ["bacl2", "h2so4"], CHEM_ALL)
        self.assertIn("ppt_baso4", events)

    def test_carbonate_needs_two_acid_portions_for_gas(self):
        _, events, ev = run("chemistry", ["na2co3", "hcl"], CHEM_ALL)
        self.assertNotIn("gas_co2", events)  # получился гидрокарбонат
        self.assertEqual(ev["view"]["ph"], 8.3)
        _, events, ev = run("chemistry", ["na2co3", "hcl", "hcl"], CHEM_ALL)
        self.assertIn("gas_co2", events)
        self.assertEqual(ev["view"]["gas"], ["CO2"])

    def test_zinc_reactions(self):
        _, events, _ = run("chemistry", ["zn", "hcl"], CHEM_ALL)
        self.assertIn("gas_h2", events)
        _, events, ev = run("chemistry", ["zn", "cuso4"], CHEM_ALL)
        self.assertIn("displ_cu", events)
        _, events, _ = run("chemistry", ["zn", "agno3"], CHEM_ALL)
        self.assertIn("displ_ag", events)
        _, events, _ = run("chemistry", ["zn", "naoh"], CHEM_ALL)
        self.assertIn("zn_alkali", events)

    def test_no_reaction_gives_no_events(self):
        _, events, _ = run("chemistry", ["nacl", "hcl"], CHEM_ALL)
        self.assertEqual(events, [])

    def test_copper_solution_is_blue_and_fades_with_dilution(self):
        _, _, ev1 = run("chemistry", ["cuso4"], CHEM_ALL)
        _, _, ev2 = run("chemistry", ["cuso4", "h2o", "h2o", "h2o"], CHEM_ALL)
        self.assertNotEqual(ev1["view"]["liquid"], sim.BASE_LIQUID)
        self.assertNotEqual(ev1["view"]["liquid"], ev2["view"]["liquid"])

    def test_item_must_be_allowed_and_flask_has_limit(self):
        state = sim.empty_state("chemistry")
        _, err = sim.apply_action("chemistry", state, "add", "naoh", None, ["hcl"])
        self.assertEqual(err, "item_not_allowed")
        for _ in range(sim.MAX_FLASK):
            state, err = sim.apply_action("chemistry", state, "add", "hcl", None, ["hcl"])
            self.assertIsNone(err)
        _, err = sim.apply_action("chemistry", state, "add", "hcl", None, ["hcl"])
        self.assertEqual(err, "flask_full")

    def test_remove_and_reset(self):
        state, _, _ = run("chemistry", ["hcl", "naoh", "phph"], CHEM_ALL)
        state, err = sim.apply_action("chemistry", state, "remove", None, 1, CHEM_ALL)
        self.assertIsNone(err)
        self.assertEqual(state["flask"], ["hcl", "phph"])
        state, _ = sim.apply_action("chemistry", state, "reset", None, None, CHEM_ALL)
        self.assertEqual(state["flask"], [])

    def test_apply_does_not_mutate_input(self):
        state = {"flask": ["hcl"]}
        sim.apply_action("chemistry", state, "add", "naoh", None, CHEM_ALL)
        self.assertEqual(state, {"flask": ["hcl"]})


class PhysicsTests(unittest.TestCase):
    def test_lamp_with_one_battery(self):
        _, events, ev = run("physics", ["battery", "bulb"], PHYS_ALL)
        self.assertIn("lamp_on", events)
        self.assertAlmostEqual(ev["view"]["current"], 0.35, places=2)

    def test_two_batteries_burn_the_bulb(self):
        _, events, ev = run("physics", ["battery", "battery", "bulb"], PHYS_ALL)
        self.assertIn("lamp_burned", events)
        self.assertEqual(ev["view"]["current"], 0.0)
        self.assertTrue(ev["view"]["burned"])

    def test_dim_lamp_with_two_resistors(self):
        _, events, _ = run("physics", ["battery", "bulb", "resistor", "resistor"], PHYS_ALL)
        self.assertIn("lamp_dim", events)

    def test_ohm_law_with_ammeter_and_voltmeter(self):
        _, events, ev = run("physics", ["battery", "resistor", "ammeter", "voltmeter"], PHYS_ALL)
        self.assertIn("ammeter_reading", ev["obs"])
        self.assertIn("voltmeter_reading", ev["obs"])
        # I = 4.5 / (0.5 + 10 + 0.1) ≈ 0.42 А, U на резисторе ≈ 4.25 В
        self.assertAlmostEqual(ev["view"]["current"], 0.42, places=2)
        resistor = [e for e in ev["view"]["elements"] if e["id"] == "resistor"][0]
        self.assertAlmostEqual(resistor["value"], 4.25, places=2)

    def test_short_circuit(self):
        _, events, ev = run("physics", ["battery", "ammeter"], PHYS_ALL)
        self.assertIn("short_circuit", events)
        self.assertGreater(ev["view"]["current"], 5)

    def test_switch_starts_open_and_toggles(self):
        steps = ["battery", "bulb", "switch"]
        state, events, ev = run("physics", steps, PHYS_ALL)
        self.assertIn("switch_open", events)
        self.assertEqual(ev["view"]["current"], 0.0)
        state, err = sim.apply_action("physics", state, "toggle", None, 2, PHYS_ALL)
        self.assertIsNone(err)
        ev = sim.evaluate("physics", state)
        self.assertGreater(ev["view"]["current"], 0)
        _, err = sim.apply_action("physics", state, "toggle", None, 0, PHYS_ALL)
        self.assertEqual(err, "bad_index")

    def test_no_battery_no_current(self):
        _, _, ev = run("physics", ["bulb", "resistor"], PHYS_ALL)
        self.assertEqual(ev["view"]["current"], 0.0)
        self.assertEqual(ev["obs"], set())

    def test_resistors_and_batteries_in_series(self):
        _, _, ev = run("physics", ["battery", "battery", "resistor", "resistor"], PHYS_ALL)
        self.assertIn("batteries_series", ev["obs"])
        self.assertIn("resistors_series", ev["obs"])


class ProgressTests(unittest.TestCase):
    def test_available_events_depend_on_teacher_choice(self):
        only_acid_base = sim.available_events("chemistry", ["hcl", "naoh"])
        self.assertIn("neutralization", only_acid_base)
        self.assertNotIn("ppt_agcl", only_acid_base)
        self.assertNotIn("ind_discolor", only_acid_base)  # нет фенолфталеина
        with_indicator = sim.available_events("chemistry", ["hcl", "naoh", "phph"])
        self.assertIn("ind_discolor", with_indicator)

    def test_every_event_is_discoverable_with_full_set(self):
        from app import catalog
        for subject, items in (("chemistry", CHEM_ALL), ("physics", PHYS_ALL)):
            expected = {e for e, ev in catalog.EVENTS.items() if ev["subject"] == subject}
            self.assertEqual(set(sim.available_events(subject, items)), expected)

    def test_replay_restores_state_and_discoveries(self):
        snapshot = {"flask": ["phph", "naoh", "hcl", "evil", "hcl"]}
        state, found = sim.replay("chemistry", snapshot, ["phph", "naoh", "hcl"])
        self.assertEqual(state["flask"], ["phph", "naoh", "hcl", "hcl"])  # "evil" отброшен
        self.assertIn("neutralization", found)
        self.assertIn("ind_discolor", found)

    def test_sanitize_rejects_garbage(self):
        self.assertEqual(sim.sanitize_state("chemistry", "string", ["hcl"]), {"flask": []})
        self.assertEqual(sim.sanitize_state("physics", {"circuit": [1, None, {"id": "x"}]}, ["battery"]),
                         {"circuit": []})
        big = {"flask": ["hcl"] * 100}
        self.assertEqual(len(sim.sanitize_state("chemistry", big, ["hcl"])["flask"]), sim.MAX_FLASK)

    def test_describe_for_ai_mentions_facts(self):
        _, _, ev = run("chemistry", ["agno3", "nacl"], CHEM_ALL)
        text = sim.describe_ru("chemistry", ev)
        self.assertIn("AgNO₃", text)
        self.assertIn("AgCl", text)
        _, _, ev = run("physics", ["battery", "bulb"], PHYS_ALL)
        self.assertIn("ток", sim.describe_ru("physics", ev))


if __name__ == "__main__":
    unittest.main()
