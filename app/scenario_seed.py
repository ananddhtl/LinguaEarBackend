"""Starter scenarios. Inserted when their slug is missing; an admin's later edits are never overwritten.

To retire one, unpublish it in the admin panel instead of deleting it (a deleted slug would be added back).
"""
import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Scenario

log = logging.getLogger("uvicorn.error")


def _s(slug, title, description, category, icon, tint, persona, openings, phrases, order):
    return {
        "slug": slug,
        "title": title,
        "description": description,
        "category": category,
        "icon": icon,
        "tint": tint,
        "persona": persona,
        "openings": dict(zip(("beginner", "intermediate", "professional"), openings)),
        "key_phrases": [{"de": de, "en": en} for de, en in phrases],
        "sort_order": order,
        "published": True,
    }


SEED = [
    _s("immigration", "Immigration Office", "Ausländerbehörde: residence permit and documents", "Official",
       "business-outline", "#6366F1",
       "You are a clerk at the Ausländerbehörde in a German city. The user has come to renew a residence permit. "
       "Ask for the passport, the current Aufenthaltstitel, the Meldebescheinigung, proof of income and a biometric "
       "photo, and explain fees and the next steps. Stay polite but official.",
       ("Guten Tag. Ihren Reisepass, bitte.",
        "Guten Tag. Was kann ich für Sie tun? Worum geht es heute?",
        "Guten Morgen. Haben Sie einen Termin? Bitte legen Sie sämtliche Unterlagen für die Verlängerung vor."),
       [("Ich möchte meinen Aufenthaltstitel verlängern.", "I would like to extend my residence permit."),
        ("Hier ist mein Reisepass.", "Here is my passport."),
        ("Welche Unterlagen brauche ich noch?", "Which documents do I still need?"),
        ("Wie lange dauert die Bearbeitung?", "How long does processing take?")], 10),
    _s("anmeldung", "Registering Your Address", "Anmeldung at the Bürgeramt after moving", "Official",
       "home-outline", "#8B5CF6",
       "You are a clerk at the Bürgeramt. The user has just moved and wants to register their address (Anmeldung). "
       "Ask for the Anmeldeformular, the passport and the Wohnungsgeberbestätigung from the landlord, check the "
       "details and explain what happens next.",
       ("Guten Tag. Sie möchten sich anmelden? Ihren Ausweis, bitte.",
        "Guten Tag. Sie sind neu umgezogen, richtig? Haben Sie das Anmeldeformular dabei?",
        "Guten Morgen. Für die Anmeldung benötige ich das ausgefüllte Formular und die Wohnungsgeberbestätigung."),
       [("Ich möchte mich anmelden.", "I would like to register my address."),
        ("Ich bin gestern umgezogen.", "I moved yesterday."),
        ("Hier ist die Bestätigung vom Vermieter.", "Here is the confirmation from the landlord."),
        ("Bekomme ich eine Meldebescheinigung?", "Will I receive a registration certificate?")], 20),
    _s("bank", "Opening a Bank Account", "Talk to an advisor about a Girokonto", "Official",
       "card-outline", "#0EA5E9",
       "You are an advisor at a German bank. The user wants to open a current account (Girokonto). Ask about "
       "identification, address and income, explain the fees, the card and online banking, and ask whether they "
       "want an overdraft limit.",
       ("Guten Tag. Möchten Sie ein Konto eröffnen?",
        "Guten Tag. Sie interessieren sich für ein Girokonto? Haben Sie Ihren Ausweis dabei?",
        "Guten Tag. Welche Kontomodelle kommen für Sie infrage, und wie hoch ist Ihr monatlicher Geldeingang?"),
       [("Ich möchte ein Konto eröffnen.", "I would like to open an account."),
        ("Was kostet das Konto pro Monat?", "What does the account cost per month?"),
        ("Bekomme ich eine Bankkarte?", "Will I get a bank card?"),
        ("Kann ich Online-Banking nutzen?", "Can I use online banking?")], 30),
    _s("cafe", "German Café", "Order coffee and cake like a local", "Daily life",
       "cafe-outline", "#F59E0B",
       "You are a friendly waiter or waitress at a traditional café in Berlin. Welcome the guest, take their order "
       "for drinks and cake, ask about sugar or milk, bring the bill and say goodbye.",
       ("Hallo! Was möchten Sie trinken?",
        "Hallo! Was darf ich Ihnen heute bringen?",
        "Guten Tag und herzlich willkommen. Haben Sie schon einen Blick in die Karte geworfen?"),
       [("Ich hätte gern einen Kaffee.", "I would like a coffee."),
        ("Was empfehlen Sie?", "What do you recommend?"),
        ("Die Rechnung, bitte.", "The bill, please."),
        ("Zusammen oder getrennt?", "Together or separately?")], 40),
    _s("bakery", "At the Bakery", "Buy bread and rolls at the Bäckerei", "Daily life",
       "storefront-outline", "#D97706",
       "You are a baker at a German Bäckerei in the morning rush. Ask what the customer wants, mention today's "
       "specials, ask how many rolls or how big a loaf, and say the price.",
       ("Guten Morgen! Was darf es sein?",
        "Guten Morgen! Was darf es heute sein? Die Brötchen sind ganz frisch.",
        "Guten Morgen. Heute haben wir ein Dinkelbrot im Angebot. Darf es sonst noch etwas sein?"),
       [("Zwei Brötchen, bitte.", "Two rolls, please."),
        ("Ein Vollkornbrot, bitte.", "A wholemeal loaf, please."),
        ("Was kostet das?", "How much is that?"),
        ("Das ist alles, danke.", "That's all, thank you.")], 50),
    _s("supermarket", "At the Supermarket", "Find things and pay at the checkout", "Daily life",
       "cart-outline", "#10B981",
       "You are a supermarket employee and cashier. Help the user find products, answer questions about offers, "
       "ask about a bag or a loyalty card, and handle payment by card or cash.",
       ("Hallo. Kann ich Ihnen helfen?",
        "Guten Tag. Suchen Sie etwas Bestimmtes?",
        "Guten Tag. Haben Sie eine Payback-Karte? Und möchten Sie bar oder mit Karte zahlen?"),
       [("Wo finde ich die Milch?", "Where do I find the milk?"),
        ("Haben Sie Tüten?", "Do you have bags?"),
        ("Kann ich mit Karte zahlen?", "Can I pay by card?"),
        ("Ich brauche keinen Kassenbon.", "I don't need a receipt.")], 60),
    _s("taxi", "Taxi Ride", "Give directions and agree on the fare", "Travel",
       "car-outline", "#10B981",
       "You are a talkative taxi driver in Frankfurt. Ask where the passenger wants to go, chat about the city and "
       "the weather, mention traffic, and say the fare at the end.",
       ("Hallo! Wohin soll es gehen?",
        "Guten Tag! Wohin darf ich Sie fahren?",
        "Guten Abend. Zum Flughafen? Bei dem Verkehr sollten wir rechtzeitig losfahren."),
       [("Zum Hauptbahnhof, bitte.", "To the main station, please."),
        ("Wie lange dauert die Fahrt?", "How long is the ride?"),
        ("Hier links, bitte.", "Left here, please."),
        ("Stimmt so.", "Keep the change.")], 70),
    _s("train", "Buying a Train Ticket", "Tickets and connections at the station", "Travel",
       "train-outline", "#0EA5E9",
       "You are a ticket agent at a German railway station. Help the user buy a ticket: ask the destination, date "
       "and time, single or return, class and whether they have a BahnCard, and mention the platform and any change.",
       ("Guten Tag. Wohin möchten Sie fahren?",
        "Guten Tag. Wohin soll die Reise gehen, und wann möchten Sie fahren?",
        "Guten Tag. Es gibt zwei Verbindungen, eine direkte und eine mit Umstieg. Haben Sie eine BahnCard?"),
       [("Eine Fahrkarte nach München, bitte.", "A ticket to Munich, please."),
        ("Einfach oder hin und zurück?", "One way or return?"),
        ("Von welchem Gleis fährt der Zug?", "From which platform does the train leave?"),
        ("Muss ich umsteigen?", "Do I have to change trains?")], 80),
    _s("doctor", "Doctor's Appointment", "Describe symptoms at the Arztpraxis", "Health",
       "medkit-outline", "#EF4444",
       "You are a doctor's receptionist, then the doctor, at a German Arztpraxis. Ask for the insurance card, ask "
       "what the problem is, since when, and whether there is pain, then explain what happens next or what to take.",
       ("Guten Tag. Haben Sie einen Termin?",
        "Guten Tag. Was fehlt Ihnen denn? Seit wann haben Sie die Beschwerden?",
        "Guten Tag. Bitte beschreiben Sie mir Ihre Symptome genau und sagen Sie, ob Sie Vorerkrankungen haben."),
       [("Ich habe einen Termin.", "I have an appointment."),
        ("Ich habe Kopfschmerzen.", "I have a headache."),
        ("Seit drei Tagen.", "For three days."),
        ("Hier ist meine Versichertenkarte.", "Here is my insurance card.")], 90),
    _s("pharmacy", "At the Pharmacy", "Ask for medicine in the Apotheke", "Health",
       "bandage-outline", "#14B8A6",
       "You are a pharmacist in a German Apotheke. Ask about the symptoms, whether the user has allergies or takes "
       "other medicine, recommend something, and explain how to take it.",
       ("Guten Tag. Wie kann ich Ihnen helfen?",
        "Guten Tag. Was brauchen Sie? Haben Sie ein Rezept?",
        "Guten Tag. Nehmen Sie derzeit andere Medikamente, und gibt es Allergien, die ich wissen sollte?"),
       [("Ich brauche etwas gegen Husten.", "I need something for a cough."),
        ("Ich habe ein Rezept.", "I have a prescription."),
        ("Wie oft muss ich es nehmen?", "How often do I have to take it?"),
        ("Gibt es Nebenwirkungen?", "Are there side effects?")], 100),
    _s("apartment", "Apartment Viewing", "Ask questions about a flat", "Housing",
       "key-outline", "#F97316",
       "You are a landlord or agent showing a flat in Germany. Show the rooms, say the rent (Kaltmiete and "
       "Nebenkosten), the deposit (Kaution) and the move-in date, and ask about the user's job and income.",
       ("Guten Tag. Kommen Sie herein. Das ist das Wohnzimmer.",
        "Guten Tag, schön, dass Sie da sind. Die Wohnung hat drei Zimmer. Haben Sie Fragen?",
        "Guten Tag. Ich benötige noch eine Schufa-Auskunft und einen Gehaltsnachweis. Wann könnten Sie einziehen?"),
       [("Wie hoch ist die Miete?", "How high is the rent?"),
        ("Sind die Nebenkosten inklusive?", "Are the extra costs included?"),
        ("Wie hoch ist die Kaution?", "How high is the deposit?"),
        ("Ab wann ist die Wohnung frei?", "From when is the flat available?")], 110),
    _s("interview", "Job Interview", "Introduce yourself to a German employer", "Work",
       "briefcase-outline", "#6366F1",
       "You are an interviewer at a German company. Ask the user to introduce themselves, about their experience, "
       "strengths and weaknesses, why they want the job, and their salary expectations. Stay professional.",
       ("Guten Tag. Bitte stellen Sie sich kurz vor.",
        "Guten Tag und danke für Ihr Kommen. Erzählen Sie mir etwas über Ihre bisherige Erfahrung.",
        "Guten Tag. Warum sollten wir uns ausgerechnet für Sie entscheiden, und wie sehen Ihre Gehaltsvorstellungen aus?"),
       [("Ich heiße ... und komme aus ...", "My name is ... and I come from ..."),
        ("Ich habe drei Jahre Erfahrung als ...", "I have three years of experience as ..."),
        ("Meine Stärke ist ...", "My strength is ..."),
        ("Meine Gehaltsvorstellung liegt bei ...", "My salary expectation is ...")], 120),
]


def seed_scenarios(db: Session) -> int:
    """Adds any starter scenario whose slug isn't in the database yet. Returns how many were added."""
    existing = set(db.scalars(select(Scenario.slug)).all())
    added = 0
    for data in SEED:
        if data["slug"] not in existing:
            db.add(Scenario(**data))
            added += 1
    if added:
        db.commit()
        log.info("Added %s starter scenario(s)", added)
    return added
