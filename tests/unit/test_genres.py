from shelfwise.ingest.genres import GENRES, map_subjects

# Real subjects from Open Library work OL19096402W (The Silent Patient).
SILENT_PATIENT = [
    "Fiction, psychological",
    "Fiction, thrillers",
    "London (england), fiction",
    "Artists, fiction",
    "Marriage, fiction",
    "New York Times bestseller",
    "Fiction, thrillers, general",
    "Family violence",
    "Fiction",
    "Marriage",
    "Artists",
    "Psychotherapy patients",
]


def test_maps_real_open_library_subjects() -> None:
    genres, tags = map_subjects(SILENT_PATIENT)

    assert genres == ["psychological thriller", "thriller"]
    assert "psychotherapy patients" in tags
    assert "marriage" in tags and tags.count("marriage") == 1
    assert not any("bestseller" in t or t == "fiction" for t in tags)


def test_nonfiction_rules_ignore_fiction_subjects() -> None:
    assert map_subjects(["World history"])[0] == ["history"]
    assert "history" not in map_subjects(["Historical fiction"])[0]
    assert map_subjects(["Psychology"])[0] == ["psychology"]
    assert map_subjects(["Fiction, psychological"])[0] == ["psychological thriller"]


def test_fiction_works_drop_nonfiction_genres() -> None:
    # Real pattern: novels carry bare subjects like "History" and "Psychology".
    genres, _ = map_subjects(["Fiction, historical", "History", "Psychology", "Philosophy"])

    assert genres == ["historical fiction"]


def test_nonfiction_works_keep_their_genres() -> None:
    genres, _ = map_subjects(["History", "Psychology", "Philosophy"])

    assert genres == ["history", "philosophy", "psychology"]


def test_true_crime_is_not_crime_fiction() -> None:
    assert map_subjects(["True crime stories"])[0] == ["true crime"]


def test_genres_come_back_in_vocabulary_order() -> None:
    genres, _ = map_subjects(["Romance", "Fantasy fiction", "Horror tales"])

    assert genres == [g for g in GENRES if g in {"romance", "fantasy", "horror"}]


def test_tags_are_capped() -> None:
    _, tags = map_subjects([f"Topic {i}" for i in range(40)])

    assert len(tags) == 30


# First 40 of 73 real subjects on Open Library work OL8193465W (A Tale of Two Cities).
TALE_OF_TWO_CITIES = [
    "British", "British and irish fiction (fictional works by one author)", "Children's fiction",
    "Criticism and interpretation", "English fiction", "English literature",
    "Executions and executioners", "Fathers and daughters", "Fiction", "classics", "Histoire",
    "Historia", "Historical fiction", "History", "Juvenile fiction", "Lookalikes", "Novela",
    "Novela inglesa", "Padre e hija", "Pères et filles", "Readers", "Roman français", "Sosies",
    "War stories", "Reign of Terror", "storming of the Bastille", "French Revolution",
    "Guillotine", "French", "Romans, nouvelles", "IIIT", "French fiction",
    "Comics & graphic novels", "British and irish drama (dramatic works by one author)",
    "Drama", "Plays", "Readers' theater", "Juvenile drama", "Children's plays, American",
    "France, history, revolution, 1789-1799, fiction",
]  # fmt: skip


def test_historical_novel_keeps_historical_fiction_and_specific_tags() -> None:
    genres, tags = map_subjects(TALE_OF_TWO_CITIES)

    assert "historical fiction" in genres
    assert "war" in genres
    assert "history" not in genres  # it's a novel, not a history book
    assert {"french revolution", "reign of terror", "guillotine"} <= set(tags)


def test_history_plus_fiction_in_one_subject_is_historical_fiction() -> None:
    assert map_subjects(["France, history, revolution, 1789-1799, fiction"])[0] == [
        "historical fiction"
    ]
    assert "historical fiction" not in map_subjects(["English fiction, history and criticism"])[0]


# Real subjects (first 14) from Open Library works.
INTRO_TO_ALGORITHMS = [
    "Algorithms", "Computer algorithms", "Computer programming", "open_syllabus_project",
    "Programming", "Algorithmes", "Programmation (Informatique)", "54.10 theoretical informatics",
    "Algorithmus", "Informatik", "Theoretische Informatik", "Algorithmentheorie",
    "COMPUTER PROGRAMS", "PROGRAMMING LANGUAGES",
]  # fmt: skip
I_ROBOT = [
    "smear campaigns", "supercomputers", "computers", "Frankenstein complex", "hyperspace",
    "heisenbugs", "asteroids", "space stations", "robots", "morality", "Science fiction",
    "Fiction",
]  # fmt: skip


def test_textbook_gets_technical_genres_and_textbook_tag() -> None:
    genres, tags = map_subjects(INTRO_TO_ALGORITHMS)

    assert {"programming", "computer science"} <= set(genres)
    assert "textbook" in tags


def test_robot_novel_is_not_a_computer_science_book() -> None:
    genres, _ = map_subjects(I_ROBOT)

    assert "science fiction" in genres
    assert not {"computer science", "artificial intelligence", "programming"} & set(genres)


def test_math_and_ai_subjects() -> None:
    assert map_subjects(["Algebras, Linear", "Textbooks", "Mathematics"]) == (
        ["mathematics"],
        ["textbook"],
    )
    assert map_subjects(["Machine learning", "Neural networks (Computer science)"])[0] == [
        "artificial intelligence",
        "computer science",
    ]
