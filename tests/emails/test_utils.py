import dns
import dns.resolver
import pytest

from itou.emails.utils import email_address_is_valid, get_email_message


VALID_ADDRS = [
    "joseph.schwartz@inclusion.gouv.fr",
    "bel.arvardan@hotmail.fr",
    "docteur.junz@laposte.fr",
    "docteur.junz+some_tag@laposte.fr",
    # As per RFC 5322 3.4.1:
    '"50n1@"@inclusion.gouv.fr',
    '" "@inclusion.gouv.fr',
    # As per RFC 6532:
    "łucasz@inclusion.gouv.fr",
    "anaïs@inclusion.gouv.fr,",
]

BAD_ADDRS = [
    "joseph.schwartz@inclusion.gouv",
    "bel.arvardan@hotmali.com",
    "docteur.junz@lapsote.fr",
    "john@xn--.com",  # IDNA: xn-- decodes to ""
]

VERY_BAD_ADDRS = [
    # Those email adresses are so bad hitting the network is not
    # needed to tell they are wrong.
    pytest.param("testemail", id="not-even-an-at-sign!"),
    pytest.param("testemail@", id="missing-domain"),
    pytest.param("john@foo..com", id="empty-label"),
    pytest.param("john@" + "x" * 64 + ".com", id="label-too-long"),
    pytest.param("john@" + ".".join(["a" * 63, "a" * 63, "a" * 63, "a" * 63]) + ".com", id="name-too-long"),
    pytest.param(r"john@a.b\0q1.c.com", id="bad-escape"),
    pytest.param(r"john@\300.com", id="bad-escape(byte>255)"),
]


def fake_resolve(qname, rdtype):
    """Forge a DNS response to avoid hitting the network.

    Rely on the presence of the qname in any of BAD_ADDRS to tell if
    it should reply or not.
    """
    assert rdtype == "MX"
    if any(qname in bad_addr for bad_addr in BAD_ADDRS):
        raise dns.resolver.NXDOMAIN
    q = dns.message.make_query(qname, dns.rdatatype.MX)
    r = dns.message.make_response(q)
    rrs = r.get_rrset(r.answer, qname, dns.rdataclass.IN, dns.rdatatype.MX, create=True)
    rrs.add(dns.rdata.from_text("IN", "MX", "1 mail.example.com."))
    return dns.resolver.Answer(qname, dns.rdatatype.MX, dns.rdataclass.IN, r)


@pytest.mark.parametrize("addr", VALID_ADDRS)
@pytest.mark.do_not_patch_accept_domain_based_on_mx
def test_check_email_should_pass(monkeypatch, addr):
    monkeypatch.setattr(dns.resolver, "resolve", fake_resolve)
    assert email_address_is_valid(addr)


@pytest.mark.parametrize("addr", BAD_ADDRS)
@pytest.mark.do_not_patch_accept_domain_based_on_mx
def test_check_email_should_fail(monkeypatch, addr):
    monkeypatch.setattr(dns.resolver, "resolve", fake_resolve)
    assert not email_address_is_valid(addr)


@pytest.mark.parametrize("addr", VERY_BAD_ADDRS)
@pytest.mark.do_not_patch_accept_domain_based_on_mx
def test_check_email_should_not_even_query(mocker, addr):
    mocker.patch("dns.resolver._Resolution.next_request")
    assert not email_address_is_valid(addr)
    dns.resolver._Resolution.next_request.assert_not_called()


def test_log_error_if_no_recipients(template_dir_fixture, caplog):
    email = get_email_message(to=[], context={}, subject="subject.txt", body="markdown_body.md")
    assert email.send() == 0

    assert "Trying to send an email without recipients, ignoring." in caplog.messages
