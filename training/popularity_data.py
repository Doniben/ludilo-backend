#!/usr/bin/env python3
"""
popularity_data.py — Base de datos de canciones populares para priorizar en la selección.

Fuentes:
- Rolling Stone 500 Greatest Songs of All Time (2021/2024)
- Ultimate Guitar: canciones más buscadas (all time)
- Guitar World: mejores riffs y solos de guitarra
- Canciones más aprendidas por guitarristas (listas de educación musical)

Formato: {artista_normalizado: {cancion_normalizada: score}}
Score: 1-10 (10 = top mundial, 1 = notable)
"""

# Score system:
# 10 = Top 10 Rolling Stone + Top Ultimate Guitar
#  9 = Top 50 Rolling Stone o Top riffs/solos Guitar World
#  8 = Top 100 Rolling Stone o muy buscada en Ultimate Guitar
#  7 = Top 200 Rolling Stone o clásico reconocido mundialmente
#  6 = Top 500 Rolling Stone o canción icónica de guitarra
#  5 = Lista "mejores para aprender guitarra" o artista top
#  4 = Canción conocida de artista importante
#  3 = Artista reconocido, canción notable

# Las canciones y artistas se normalizan: lowercase, sin "the", sin acentos,
# sin caracteres especiales, espacios simplificados.

POPULAR_SONGS = {
    # === TIER 10: Absolutas leyendas ===
    ("nirvana", "smells like teen spirit"): 10,
    ("led zeppelin", "stairway to heaven"): 10,
    ("eagles", "hotel california"): 10,
    ("pink floyd", "comfortably numb"): 10,
    ("queen", "bohemian rhapsody"): 10,
    ("guns n roses", "sweet child o mine"): 10,
    ("deep purple", "smoke on the water"): 10,
    ("beatles", "hey jude"): 10,
    ("beatles", "let it be"): 10,
    ("metallica", "nothing else matters"): 10,
    
    # === TIER 9: Iconos de guitarra ===
    ("metallica", "enter sandman"): 9,
    ("metallica", "master of puppets"): 9,
    ("metallica", "one"): 9,
    ("ac dc", "back in black"): 9,
    ("ac dc", "thunderstruck"): 9,
    ("ac dc", "highway to hell"): 9,
    ("led zeppelin", "whole lotta love"): 9,
    ("led zeppelin", "kashmir"): 9,
    ("pink floyd", "wish you were here"): 9,
    ("pink floyd", "another brick in the wall"): 9,
    ("guns n roses", "november rain"): 9,
    ("guns n roses", "paradise city"): 9,
    ("jimi hendrix", "purple haze"): 9,
    ("jimi hendrix", "all along the watchtower"): 9,
    ("jimi hendrix", "voodoo child"): 9,
    ("eric clapton", "tears in heaven"): 9,
    ("eric clapton", "layla"): 9,
    ("eric clapton", "wonderful tonight"): 9,
    ("black sabbath", "iron man"): 9,
    ("black sabbath", "paranoid"): 9,
    ("van halen", "eruption"): 9,
    ("van halen", "jump"): 9,
    ("dire straits", "sultans of swing"): 9,
    ("dire straits", "money for nothing"): 9,
    ("red hot chili peppers", "californication"): 9,
    ("red hot chili peppers", "under the bridge"): 9,
    ("nirvana", "come as you are"): 9,
    ("oasis", "wonderwall"): 9,
    ("oasis", "dont look back in anger"): 9,
    ("queen", "we will rock you"): 9,
    ("queen", "we are the champions"): 9,
    
    # === TIER 8: Clásicos reconocidos mundialmente ===
    ("beatles", "yesterday"): 8,
    ("beatles", "come together"): 8,
    ("beatles", "here comes the sun"): 8,
    ("beatles", "while my guitar gently weeps"): 8,
    ("beatles", "blackbird"): 8,
    ("rolling stones", "satisfaction"): 8,
    ("rolling stones", "paint it black"): 8,
    ("rolling stones", "sympathy for the devil"): 8,
    ("bob dylan", "knockin on heavens door"): 8,
    ("bob dylan", "blowin in the wind"): 8,
    ("elvis presley", "cant help falling in love"): 8,
    ("fleetwood mac", "dreams"): 8,
    ("fleetwood mac", "the chain"): 8,
    ("john lennon", "imagine"): 8,
    ("u2", "one"): 8,
    ("u2", "with or without you"): 8,
    ("u2", "where the streets have no name"): 8,
    ("coldplay", "yellow"): 8,
    ("coldplay", "the scientist"): 8,
    ("coldplay", "viva la vida"): 8,
    ("radiohead", "creep"): 8,
    ("radiohead", "paranoid android"): 8,
    ("red hot chili peppers", "scar tissue"): 8,
    ("red hot chili peppers", "snow hey oh"): 8,
    ("red hot chili peppers", "otherside"): 8,
    ("foo fighters", "everlong"): 8,
    ("foo fighters", "the pretender"): 8,
    ("green day", "basket case"): 8,
    ("green day", "boulevard of broken dreams"): 8,
    ("green day", "american idiot"): 8,
    ("iron maiden", "the trooper"): 8,
    ("iron maiden", "hallowed be thy name"): 8,
    ("iron maiden", "fear of the dark"): 8,
    ("iron maiden", "run to the hills"): 8,
    ("ozzy osbourne", "crazy train"): 8,
    ("pearl jam", "alive"): 8,
    ("pearl jam", "black"): 8,
    ("pearl jam", "jeremy"): 8,
    ("system of a down", "chop suey"): 8,
    ("system of a down", "toxicity"): 8,
    ("linkin park", "in the end"): 8,
    ("linkin park", "numb"): 8,
    ("cranberries", "zombie"): 8,
    ("animals", "house of the rising sun"): 8,
    ("kansas", "dust in the wind"): 8,
    ("lynyrd skynyrd", "free bird"): 8,
    ("lynyrd skynyrd", "sweet home alabama"): 8,
    ("santana", "smooth"): 8,
    ("santana", "black magic woman"): 8,
    ("cream", "sunshine of your love"): 8,
    ("cream", "crossroads"): 8,
    
    # === TIER 7: Muy populares, siempre buscadas ===
    ("metallica", "fade to black"): 7,
    ("metallica", "the unforgiven"): 7,
    ("metallica", "for whom the bell tolls"): 7,
    ("metallica", "seek and destroy"): 7,
    ("metallica", "battery"): 7,
    ("metallica", "sanitarium"): 7,
    ("megadeth", "holy wars"): 7,
    ("megadeth", "symphony of destruction"): 7,
    ("megadeth", "tornado of souls"): 7,
    ("megadeth", "hangar 18"): 7,
    ("slayer", "raining blood"): 7,
    ("slayer", "angel of death"): 7,
    ("pantera", "walk"): 7,
    ("pantera", "cowboys from hell"): 7,
    ("pantera", "cemetery gates"): 7,
    ("dream theater", "pull me under"): 7,
    ("dream theater", "metropolis part 1"): 7,
    ("tool", "schism"): 7,
    ("tool", "lateralus"): 7,
    ("alice in chains", "rooster"): 7,
    ("alice in chains", "man in the box"): 7,
    ("alice in chains", "would"): 7,
    ("soundgarden", "black hole sun"): 7,
    ("nirvana", "heart shaped box"): 7,
    ("nirvana", "lithium"): 7,
    ("rage against the machine", "killing in the name"): 7,
    ("rage against the machine", "bulls on parade"): 7,
    ("muse", "hysteria"): 7,
    ("muse", "knights of cydonia"): 7,
    ("muse", "plug in baby"): 7,
    ("blink 182", "all the small things"): 7,
    ("blink 182", "dammit"): 7,
    ("offspring", "self esteem"): 7,
    ("offspring", "the kids arent alright"): 7,
    ("weezer", "say it aint so"): 7,
    ("weezer", "buddy holly"): 7,
    ("arctic monkeys", "do i wanna know"): 7,
    ("arctic monkeys", "r u mine"): 7,
    ("white stripes", "seven nation army"): 7,
    ("aerosmith", "dream on"): 7,
    ("aerosmith", "walk this way"): 7,
    ("bon jovi", "livin on a prayer"): 7,
    ("bon jovi", "wanted dead or alive"): 7,
    ("scorpions", "still loving you"): 7,
    ("scorpions", "wind of change"): 7,
    ("def leppard", "pour some sugar on me"): 7,
    ("joe satriani", "always with me always with you"): 7,
    ("joe satriani", "surfing with the alien"): 7,
    ("steve vai", "for the love of god"): 7,
    ("yngwie malmsteen", "far beyond the sun"): 7,
    ("gary moore", "still got the blues"): 7,
    ("gary moore", "parisienne walkways"): 7,
    ("john mayer", "gravity"): 7,
    ("john mayer", "slow dancing in a burning room"): 7,
    ("srv", "pride and joy"): 7,
    ("stevie ray vaughan", "pride and joy"): 7,
    ("bb king", "the thrill is gone"): 7,
    ("hendrix", "little wing"): 7,
    ("jimi hendrix", "little wing"): 7,
    ("pink floyd", "time"): 7,
    ("pink floyd", "money"): 7,
    ("led zeppelin", "black dog"): 7,
    ("led zeppelin", "rock and roll"): 7,
    ("led zeppelin", "heartbreaker"): 7,
    ("deep purple", "highway star"): 7,
    ("deep purple", "child in time"): 7,
    ("rush", "tom sawyer"): 7,
    ("rush", "yyz"): 7,
    ("rush", "spirit of radio"): 7,
    ("who", "baba oriley"): 7,
    ("who", "pinball wizard"): 7,
    
    # === TIER 6: Canciones icónicas de guitarra / educativas ===
    ("eric clapton", "cocaine"): 6,
    ("eric clapton", "crossroads"): 6,
    ("clapton", "wonderful tonight"): 6,
    ("mark knopfler", "going home"): 6,
    ("chet atkins", "mr sandman"): 6,
    ("tommy emmanuel", "classical gas"): 6,
    ("mason williams", "classical gas"): 6,
    ("francisco tarrega", "lagrima"): 6,
    ("tarrega", "recuerdos de la alhambra"): 6,
    ("bach", "bourree in e minor"): 6,
    ("bach", "prelude in d minor"): 6,
    ("beethoven", "fur elise"): 6,
    ("pachelbel", "canon in d"): 6,
    ("vivaldi", "four seasons"): 6,
    ("rodrigo", "concierto de aranjuez"): 6,
    ("scott joplin", "the entertainer"): 6,
    ("sor", "estudio"): 6,
    ("villa lobos", "prelude"): 6,
    ("carulli", "andante"): 6,
    ("malaguena", "malaguena"): 6,
    ("traditional", "romance"): 6,
    ("traditional", "romanza"): 6,
    ("traditional", "greensleeves"): 6,
    ("simon garfunkel", "sound of silence"): 6,
    ("simon and garfunkel", "sound of silence"): 6,
    ("cat stevens", "wild world"): 6,
    ("cat stevens", "father and son"): 6,
    ("tracy chapman", "fast car"): 6,
    ("jeff buckley", "hallelujah"): 6,
    ("leonard cohen", "hallelujah"): 6,
    ("unplugged", "tears in heaven"): 6,
    ("clapton", "tears in heaven"): 6,
    ("james taylor", "fire and rain"): 6,
    ("neil young", "heart of gold"): 6,
    ("neil young", "old man"): 6,
    ("bob marley", "redemption song"): 6,
    ("bob marley", "no woman no cry"): 6,
    
    # === TIER 5: Artistas top, canciones para aprender ===
    ("red hot chili peppers", "dani california"): 5,
    ("red hot chili peppers", "by the way"): 5,
    ("red hot chili peppers", "give it away"): 5,
    ("foo fighters", "learn to fly"): 5,
    ("foo fighters", "best of you"): 5,
    ("muse", "starlight"): 5,
    ("muse", "time is running out"): 5,
    ("radiohead", "karma police"): 5,
    ("radiohead", "no surprises"): 5,
    ("nirvana", "in bloom"): 5,
    ("nirvana", "about a girl"): 5,
    ("pearl jam", "even flow"): 5,
    ("soundgarden", "spoonman"): 5,
    ("audioslave", "like a stone"): 5,
    ("audioslave", "cochise"): 5,
    ("smashing pumpkins", "today"): 5,
    ("smashing pumpkins", "1979"): 5,
    ("incubus", "drive"): 5,
    ("incubus", "wish you were here"): 5,
    ("creed", "with arms wide open"): 5,
    ("staind", "its been awhile"): 5,
    ("3 doors down", "kryptonite"): 5,
    ("nickelback", "how you remind me"): 5,
    ("kings of leon", "use somebody"): 5,
    ("kings of leon", "sex on fire"): 5,
    ("the killers", "mr brightside"): 5,
    ("franz ferdinand", "take me out"): 5,
    ("interpol", "obstacle 1"): 5,
    ("strokes", "last nite"): 5,
    ("strokes", "reptilia"): 5,
    ("jack johnson", "better together"): 5,
    ("jack johnson", "banana pancakes"): 5,
    ("john mayer", "waiting on the world to change"): 5,
    ("ed sheeran", "photograph"): 5,
    ("ed sheeran", "thinking out loud"): 5,
    ("passenger", "let her go"): 5,
    ("hozier", "take me to church"): 5,
    ("iron maiden", "aces high"): 5,
    ("iron maiden", "wasted years"): 5,
    ("iron maiden", "number of the beast"): 5,
    ("judas priest", "breaking the law"): 5,
    ("judas priest", "painkiller"): 5,
    ("motorhead", "ace of spades"): 5,
    ("rammstein", "du hast"): 5,
    ("korn", "freak on a leash"): 5,
    ("slipknot", "duality"): 5,
    ("slipknot", "psychosocial"): 5,
    ("avenged sevenfold", "bat country"): 5,
    ("avenged sevenfold", "afterlife"): 5,
    ("trivium", "in waves"): 5,
    ("bullet for my valentine", "tears dont fall"): 5,
    ("in flames", "take this life"): 5,
    ("opeth", "blackwater park"): 5,
    ("gojira", "flying whales"): 5,
    ("mastodon", "blood and thunder"): 5,
    ("lamb of god", "laid to rest"): 5,
}

# Artistas que tienen alta prioridad general (cualquier canción de ellos suma puntos)
PRIORITY_ARTISTS = {
    "metallica": 4,
    "iron maiden": 4,
    "red hot chili peppers": 4,
    "beatles": 4,
    "led zeppelin": 4,
    "pink floyd": 4,
    "nirvana": 3,
    "guns n roses": 3,
    "ac dc": 3,
    "queen": 3,
    "eric clapton": 3,
    "jimi hendrix": 3,
    "black sabbath": 3,
    "megadeth": 3,
    "dream theater": 3,
    "joe satriani": 3,
    "steve vai": 3,
    "rolling stones": 3,
    "eagles": 3,
    "van halen": 3,
    "dire straits": 3,
    "deep purple": 3,
    "pearl jam": 3,
    "soundgarden": 3,
    "alice in chains": 3,
    "foo fighters": 3,
    "radiohead": 3,
    "muse": 3,
    "oasis": 3,
    "coldplay": 3,
    "green day": 2,
    "blink 182": 2,
    "system of a down": 2,
    "slayer": 2,
    "pantera": 2,
    "tool": 2,
    "rage against the machine": 2,
    "aerosmith": 2,
    "scorpions": 2,
    "bon jovi": 2,
    "def leppard": 2,
    "rush": 2,
    "yngwie malmsteen": 2,
    "john mayer": 2,
    "santana": 2,
    "hendrix": 2,
}


def normalize_for_matching(text: str) -> str:
    """Normaliza texto para matching flexible."""
    import re
    text = text.lower().strip()
    # Quitar "the " al inicio
    text = re.sub(r'^the\s+', '', text)
    # Quitar paréntesis y su contenido
    text = re.sub(r'\([^)]*\)', '', text)
    # Quitar caracteres especiales
    text = re.sub(r'[^\w\s]', '', text)
    # Múltiples espacios → uno
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def get_popularity_score(artist: str, title: str) -> int:
    """
    Retorna un score de popularidad (0-10) para una canción.
    
    Args:
        artist: Nombre del artista (sin normalizar)
        title: Título de la canción (sin normalizar)
    
    Returns:
        Score 0-10 (0 = no encontrada en listas)
    """
    artist_norm = normalize_for_matching(artist)
    title_norm = normalize_for_matching(title)
    
    # Buscar match exacto en POPULAR_SONGS
    best_score = 0
    
    for (a, t), score in POPULAR_SONGS.items():
        # Match flexible: si el artista y título contienen las keywords
        if a in artist_norm or artist_norm in a:
            if t in title_norm or title_norm in t:
                best_score = max(best_score, score)
    
    # Si no hay match por canción, buscar por artista
    if best_score == 0:
        for a, score in PRIORITY_ARTISTS.items():
            if a in artist_norm or artist_norm in a:
                best_score = max(best_score, score)
                break
    
    return best_score


def get_all_popular_songs() -> dict:
    """Retorna todas las canciones populares como dict."""
    return POPULAR_SONGS


def get_priority_artists() -> dict:
    """Retorna artistas prioritarios."""
    return PRIORITY_ARTISTS


# Test rápido
if __name__ == "__main__":
    test_cases = [
        ("Metallica", "Nothing Else Matters"),
        ("Metallica", "Enter Sandman"),
        ("Red Hot Chili Peppers", "Californication"),
        ("Iron Maiden", "The Trooper"),
        ("Led Zeppelin", "Stairway to Heaven"),
        ("Dream Theater", "Pull Me Under"),
        ("Unknown Artist", "Random Song"),
        ("Metallica", "Some Unknown Song"),
        ("Joe Satriani", "Always With Me Always With You"),
        ("Eagles", "Hotel California"),
    ]
    
    print(f"{'Artista':<30} {'Canción':<30} {'Score':>5}")
    print("-" * 67)
    for artist, title in test_cases:
        score = get_popularity_score(artist, title)
        print(f"{artist:<30} {title:<30} {score:>5}")
    
    print(f"\nTotal canciones en DB: {len(POPULAR_SONGS)}")
    print(f"Total artistas prioritarios: {len(PRIORITY_ARTISTS)}")
