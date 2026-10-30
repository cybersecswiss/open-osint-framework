# Companies & people

Every other module starts from a technical selector — a username, a domain, a
hash, a wallet. This one starts from a **name**, which is the entry point a
procurement, sanctions-evasion or shell-company case actually has.

Pick the query type **Company name** or **Person name**, type the name, and
tick the *Companies & people* module. All five tools are keyless.

## What each tool answers

| Tool | The question it answers | Rating |
|---|---|---|
| **Swiss register (SHAB)** | Does this company exist in Switzerland, who signs for it, from what address, and is it still registered? | A |
| **Group structure (GLEIF)** | Who owns it, what does it own, and under what other names is it registered? | A |
| **Sanctions screening** | Is this name on the EU or US sanctions lists, under which programme? | A |
| **Wikidata affiliations** | Who runs it, who holds a stake, what else belongs to the same group? | C |
| **Swiss directory** | Where does it physically answer the phone? | B |

## A worked example

Suppose you search for the (fictional) company **Muster Trading SA** as a
*Company name*. Such a search typically returns:

* the **Geneva branch** from the Swiss register — its UID (`CHE-…`), address,
  the cantonal register it is entered at and, where applicable, the date it
  was **deleted** and why;
* the **named signatories**, for example a director with individual signing
  authority, with his stated nationality and place of residence, and the
  exact sentence the register printed;
* the **group**: the foreign parent under its LEI, its names in other
  scripts and Latin variants, and its subsidiaries;
* the **leadership** and shareholdings from Wikidata.

That is four different kinds of record about one organisation, joined into one
graph — and every one of them carries the link it came from.

## Reading the results carefully

**The company is a record. The people are parsed from prose.** Swiss register
publications name officers in a formulaic sentence ("Signature individuelle a
été conférée à …", "…, von Zug, in Bern, Mitglied des Verwaltungsrates"), not
in a structured field. The tool extracts them conservatively and attaches the
**exact sentence** to every person it produces, under `register_statement`.
Read that sentence before you rely on the name. This is also why people come
back with a lower confidence than the company they belong to.

**A sanctions "no hit" is not a clearance.** Matching is deliberately exact:
every word of your query must appear in the listed name. That avoids accusing
the wrong person, and it means a **differently transliterated** spelling will
not be found. Иванов and Ivanov are not matched to each other by the
machine — that inference is yours to make, and to document. The tool always
says how many names it checked.

**Wikidata is a lead, not a record.** It is community-maintained. Use it to
find *where to look* — a subsidiary, a chairperson, an owner — and then
confirm that finding in a register.

**A missing directory entry proves nothing.** An unlisted number is absent
from tel.search.ch exactly like a non-existent one.

## Where this fits in a case

The natural order:

1. **Register first** — it gives you the legal entity, the address and the
   people, all citable.
2. **Group structure** — the parent and the sister companies are usually
   where the actual counterparty sits.
3. **Sanctions screening** on every name the first two steps produced, not
   just the one you started with.
4. **Then pivot technically**: the address and the people feed
   [ordinary searches](03-searching.md) — the company domain into `infra` and
   `theharvester`, an officer's name into the alias tools, the phone number
   into the messenger tools.

The **Sanctions evasion / procurement** playbook sets this up in one click.

## A word on care

From here on you are working with **personal data about real people**. A
person named as an officer in a commercial register is a public fact. That the
same person is involved in an offence is a claim — yours, and one you have to
be able to support.

The platform keeps those apart deliberately: tools collect, a human links, and
the note field on the node is where your reasoning belongs. Use it. In six
months it will be the only record of *why* you connected two findings, and
that is exactly what a case file has to be able to show.

See also: [Assessing findings](12-assessing-findings.md) ·
[Running a search](03-searching.md) · [Exporting a case](14-exporting.md)
