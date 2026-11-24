# Copyright 2026 unpatterned.org
# SPDX-License-Identifier: Apache-2.0

"""House numbers, units and street-less places as Nigerian, Kenyan and Ghanaian provider
lists write them.

The shapes come from health-insurance provider lists; the names are invented.
"""

from __future__ import annotations

import pytest
from arche.addr import extract_unit, parse_address, parse_locality


def _c(text: str):
    a = parse_address(text)
    assert a is not None, text
    return a.components


@pytest.mark.parametrize(("text", "number"), [
    ("4B, Adeleke Crescent, Temanu", "4B"),          # a comma after the number
    ("12, Ajala Lane, Temanu", "12"),
    ("62-80 Obodo Road, Temanu", "62-80"),           # a range
    ("1/5 Kanyiri Street, Temanu", "1/5"),           # a pair
    ("NW4/183 Ashgrove Street, Temanu", "NW4/183"),  # a layout code
    ("Plot CL-6 Pond Street, Temanu", "CL-6"),
    ("No. 3 Ajala Lane, Temanu", "3"),               # the word is left out
    ("No 3, Ajala Lane, Temanu", "3"),
    ("Plot 14 Ajala Lane, Temanu", "14"),
    ("7B Allen Avenue, Ikeja, Lagos", "7B"),         # unchanged
])
def test_house_number(text, number):
    assert _c(text).street_number == number


def test_no_needs_a_digit():
    c = _c("North Ajala Lane, Temanu")
    assert c.plot is None and c.street_number is None
    assert c.street == "North Ajala Lane"


def test_a_number_inside_a_word_is_not_a_house_number():
    assert _c("Ajala Lane, Temanu").street_number is None


@pytest.mark.parametrize(("text", "unit"), [
    ("5th Floor, 18 Moi Avenue, Mombasa", "5th Floor"),
    ("18 Moi Avenue, Room 6, Mombasa", "Room 6"),
    ("Unit 4, Ajala Lane, Temanu", "Unit 4"),
])
def test_unit_in_a_street_address(text, unit):
    assert _c(text).unit == unit


def test_unit_on_another_line_is_not_attached():
    a = parse_address("Shop 12\n\n18 Moi Avenue, Mombasa")
    assert a is not None and a.components.unit is None


def test_plot_is_not_a_unit():
    assert _c("Plot 14 Ajala Lane, Temanu").unit is None


@pytest.mark.parametrize(("text", "unit"), [
    ("Kanyiri Plaza 4th floor", "4th floor"),
    ("Temanu doctors plaza room 405", "room 405"),
    ("Obodo House, Shop 12", "Shop 12"),
    ("Ashgrove Centre, ground floor", "ground floor"),
])
def test_extract_unit_without_a_street(text, unit):
    assert parse_address(text) is None
    assert extract_unit(text) == unit


def test_extract_unit_none():
    assert extract_unit("Northern Bypass, Temanu") is None


@pytest.mark.parametrize(("text", "city", "neighborhood"), [
    ("Temanu near Obodo Filling Station", "Temanu", None),     # a landmark after the town
    ("Temanu Opp Kanyiri Hotel", "Temanu", None),               # the short form
    ("Behind Ajala Church, Temanu", "Temanu", None),            # a landmark before it
    ("Ashgrove, Temanu", "Temanu", "Ashgrove"),                 # by position, no gazetteer
    ("Ashgrove, Kanyiri Road", "Ashgrove", None),               # a road is not a place
    ("Obodo Plaza, Temanu", "Temanu", None),                    # nor is a building
    ("Temanu- Ashgrove Junction", "Temanu", None),              # a dash as a comma
    ("Ashgrove, Temanu, Obodo State", "Temanu", "Ashgrove"),    # the region is not the town
    ("Temanu town", "Temanu town", None),
])
def test_parse_locality(text, city, neighborhood):
    c = parse_locality(text)
    assert c is not None
    assert (c.city, c.neighborhood) == (city, neighborhood)


def test_parse_locality_keeps_the_landmark():
    c = parse_locality("Temanu near Obodo Filling Station")
    assert c.anchor == "near Obodo Filling Station"


@pytest.mark.parametrize("text", [
    "Opposite Obodo Filling Station",      # nothing but a landmark
    "Obodo Plaza",
    "please see the attached list of branches for each region",  # too long to be a place
])
def test_parse_locality_none(text):
    assert parse_locality(text) is None


def test_parse_locality_along_names_the_road():
    c = parse_locality("Ashgrove along Kanyiri Road")
    assert (c.street, c.city, c.anchor) == ("Kanyiri Road", "Ashgrove", None)


def test_parse_locality_larger_to_smaller():
    # Kumasi is in the gazetteer and written first; the places after it are inside it.
    c = parse_locality("Kumasi Ashgrove Temanu")
    assert (c.city, c.neighborhood) == ("Kumasi", "Ashgrove Temanu")
    # The usual order is unchanged: a town later on is the city.
    c = parse_locality("Ashgrove, Kumasi")
    assert (c.city, c.neighborhood) == ("Kumasi", "Ashgrove")


@pytest.mark.parametrize(("text", "city", "anchor"), [
    # A landmark between the street and the town is passed over, not taken as the town.
    ("6 Ajala Street, OFF OBODO/KANYIRI ROAD, TEMANU", "TEMANU", "OFF OBODO/KANYIRI ROAD"),
    ("1 Ajala Lane, Off Obodo B/Stop, Temanu", "Temanu", "Off Obodo B/Stop"),
    ("26 Ajala Street, Of Kanyiri Jones (Obodo Bus Stop), Temanu", "Temanu",
     "Of Kanyiri Jones (Obodo Bus Stop)"),
    ("8 Ajala Close, Near Obodo Cinema, Temanu", "Temanu", "Near Obodo Cinema"),
    # A second road is a landmark too.
    ("8 Ajala Close, Kanyiri Road, Temanu", "Temanu", "Kanyiri Road"),
    # A P.O. box between them is passed over.
    ("51 Ajala Road, P.O. Box 555, Temanu", "Temanu", None),
    ("89 Ajala Street, P.M.B. 6185, Temanu", "Temanu", None),
])
def test_town_after_a_landmark(text, city, anchor):
    c = _c(text)
    assert (c.city, c.anchor) == (city, anchor)


def test_a_landmark_alone_after_the_street_is_not_a_town():
    c = _c("65 Ajala Street, Off Obodo Street, Behind Kanyiri Garage")
    assert c.city is None and c.anchor == "Off Obodo Street"



@pytest.mark.parametrize(("text", "number", "street", "city"), [
    # All capitals and all lowercase read as the mixed-case form does, and come back as written.
    ("6 AJALA STREET, OFF KANYIRI ROAD, TEMANU", "6", "AJALA STREET", "TEMANU"),
    ("6 ajala street, off kanyiri road, temanu", "6", "ajala street", "temanu"),
    ("FC 7, AJALA STREET, TEMANU", "FC 7", "AJALA STREET", "TEMANU"),     # the code stays
    ("fc 7, ajala street, temanu", "fc 7", "ajala street", "temanu"),
    ("NO 7, AJALA STREET, TEMANU", "7", "AJALA STREET", "TEMANU"),        # the word does not
    ("SW7/217, AJALA STREET, TEMANU", "SW7/217", "AJALA STREET", "TEMANU"),
])
def test_all_capitals_and_all_lowercase(text, number, street, city):
    c = _c(text)
    assert (c.street_number, c.street, c.city) == (number, street, city)


def test_the_raw_span_is_as_written():
    a = parse_address("6 AJALA STREET, TEMANU")
    assert a.raw == "6 AJALA STREET, TEMANU"


@pytest.mark.parametrize(("text", "street", "city"), [
    # A road without capitals in an otherwise mixed-case address, as Kenyan lists write it.
    ("Kanyiri road, Temanu town", "Kanyiri road", "Temanu town"),
    ("Obodo Plaza, ashgrove avenue", "ashgrove avenue", None),
    ("3rd Floor Obodo House, Kanyiri street", "Kanyiri street", None),
])
def test_lowercase_road(text, street, city):
    c = _c(text)
    assert (c.street, c.city) == (street, city)


@pytest.mark.parametrize("text", [
    "She was on the long road, then went home",
    "Please meet us by the main road, thanks",
    "It is a dirt road, they said",
])
def test_lowercase_road_not_in_prose(text):
    a = parse_address(text)
    assert a is None or a.components.street is None


@pytest.mark.parametrize(("text", "street"), [
    ("3 Ajala Drive Off Kanyiri Road, Temanu", "Ajala Drive"),     # not across "Off"
    ("Obodo Estate Ajala Avenue, Temanu", "Ajala Avenue"),         # nor an estate
    ("12 Estate Road, Temanu", "Estate Road"),                     # unless it is the road's name
    ("12 Clinic Road, Temanu", "Clinic Road"),
])
def test_street_name_bounds(text, street):
    assert _c(text).street == street


def test_a_bus_stop_is_not_an_area():
    c = _c("3 Ajala Street, Kanyiri Bus-Stop, Temanu")
    assert (c.neighborhood, c.city) == (None, "Temanu")


def test_an_estate_straight_after_the_road_is_the_area():
    c = _c("7 Ajala Street Kanyiri Estate, Temanu")
    assert (c.neighborhood, c.city) == ("Kanyiri Estate", "Temanu")


def test_dotted_initials_in_an_area():
    c = _c("11 Ajala Road, Kanyiri G.R.A., Temanu")
    assert (c.neighborhood, c.city) == ("Kanyiri G.R.A", "Temanu")


def test_lowercase_road_not_across_a_landmark_word():
    # "of" here is "off": the road is where the place is off, not its own road.
    a = parse_address("Temanu, Ashgrove of Kanyiri road")
    assert a is None or a.components.street is None
