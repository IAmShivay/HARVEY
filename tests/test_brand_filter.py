from types import SimpleNamespace

from harvey.brand_filter import clean_name, enabled, judge

STORE_US = ('<a href="/products/soap">Add to cart</a> <a href="/cart">Cart</a> '
            "Prices in USD. Austin, TX 78701")


def test_us_store_is_kept():
    keep, _ = judge("Ashley Marie Soap", "ashleymariesoap.com", STORE_US)
    assert keep


def test_agency_is_removed_even_with_a_cart():
    html = STORE_US + " Shopify experts agency. Our clients. Case studies."
    keep, reason = judge("Ranosys", "ranosys.com", html)
    assert not keep and "service" in reason


def test_saas_is_removed():
    html = "Book a demo. Start your free trial. Pricing plans. USD"
    keep, _ = judge("Aitrillion", "aitrillion.com", html)
    assert not keep


def test_listicle_name_is_removed():
    keep, reason = judge("15 Best American-Made Home Goods Brands", "buyamerican.com", STORE_US)
    assert not keep and "list" in reason


def test_non_us_domain_is_removed():
    keep, _ = judge("Tracey Cooper", "traceycooper.co.uk", STORE_US)
    assert not keep


def test_store_without_us_signals_is_removed():
    keep, reason = judge("Shop", "shop.example", '<a href="/cart">Add to cart</a> checkout')
    assert not keep and "US" in reason


def test_unreachable_site_is_removed():
    keep, _ = judge("Gone", "gone.example", None)
    assert not keep


def test_do_not_contact_wins():
    keep, reason = judge("Belkin", "belkin.com", STORE_US, blocked_by="belkin.com")
    assert not keep and "do_not_contact" in reason


def test_off_by_default():
    assert not enabled(SimpleNamespace(icp=SimpleNamespace()))
    assert enabled(SimpleNamespace(icp=SimpleNamespace(us_brand_filter=True)))


def test_clean_name_trims_page_titles():
    assert clean_name("Ceptics Travel Plug Adapters 🔌 Connecting the World", "ceptics.com") == "Ceptics"
    assert clean_name("HueGah Home | Mid-Century Decor", "huegahhome.com") == "HueGah Home"
    assert clean_name("About Glimmer Goddess®", "glimmergoddess.com") == "Glimmer Goddess"
    assert clean_name("NutraMedix® Official Site", "nutramedix.com") == "NutraMedix"
    assert clean_name("1620 Workwear, Inc", "1620usa.com") == "1620 Workwear"


def test_clean_name_leaves_real_names_alone():
    assert clean_name("Viva Workshop", "vivaworkshop.com") == "Viva Workshop"
    assert clean_name("Girl Tribe Co", "girltribeco.com") == "Girl Tribe Co"
    assert clean_name("Ashley Marie Soap", "ashleymariesoap.com") == "Ashley Marie Soap"
