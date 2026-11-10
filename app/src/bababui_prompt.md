# Task

Convert the supplied speaker-labeled transcript into a deposition transcript using
the examination, Q/A, colloquy, and plain-text layout below. Apply the punctuation,
capitalization, spelling, and number rules in the reference. The cleanup,
paragraphing, and output layout
specified here take precedence over conflicting rules and examples in the
reference, including rules for retaining or punctuating false starts and fillers.
Use only the supplied transcript and instructions. Do not add facts from outside
the transcript or treat reference examples as facts about this examination.

## Speaker identification and examination labels

Identify the witness, examining attorney, other attorneys, and reporter from
explicit introductions, supplied speaker information, and clear conversational
roles. Keep the original speaker identifiers throughout; never replace them with
personal names, titles, THE WITNESS, or THE REPORTER, even when identities are
known. Use uppercase SPEAKER N in headings and colloquy, preserving the input's
speaker number. For example, use BY SPEAKER 2: and SPEAKER 1:. Maintain a consistent
mapping from each input speaker to their role. If a role is uncertain, retain
that speaker identifier as a colloquy label rather than guessing Q or A.
Use introductions to establish these roles before removing irrelevant introductory
speech from the output as described below.

At the beginning of an identifiable examination, insert a centered EXAMINATION
heading, followed on the next line by a flush-left BY SPEAKER N: line.
Use Q for the examining attorney's turns addressed to the witness and A for the
witness's turns within that examination. These labels reflect roles, not sentence
punctuation: an attorney's statement can be Q, and a witness's clarifying question
can be A. Do not alternate labels mechanically or merge distinct speaker turns.

Use uppercase SPEAKER N: labels for colloquy, including objections,
attorney-to-attorney exchanges, procedural discussion, reporter remarks, and
witness speech outside Q/A examination. Keep the same speaker numbers used in
the input. An objection does not make its speaker the new examining attorney.
Continue colloquy labels through the intervening exchange.

When questioning resumes after colloquy or a recess, insert a fresh BY SPEAKER N:
line for the current examiner before returning to Q/A. Do not repeat EXAMINATION for
a simple resumption. When a different attorney begins an examination, insert a
new EXAMINATION heading and their BY line. When a previous examiner returns for
additional questioning after another attorney's examination, use FURTHER
EXAMINATION and the returning examiner's BY line. Follow the conversational
transition, not merely a change of speaker.

## Plain-text layout

Use spaces, not tabs. Write each paragraph on one logical line, without adding
line breaks to fit a display width. Center EXAMINATION and FURTHER EXAMINATION
within a 56-character field. Keep BY lines flush left.

Begin each Q/A paragraph with five spaces, Q or A, then four spaces. Begin each
colloquy paragraph with five spaces, its uppercase label and colon, then two spaces.
A new paragraph within the same speaker turn begins with ten spaces and no
repeated Q/A or speaker label; use such paragraphs only when the speaker changes
to a completely different topic. A sentence ending, brief acknowledgment, pause,
filler removal, false-start removal, or related follow-up question does not create
a new paragraph. Keep
"Thank you.  You are acting in the capacity of qualified medical evaluator..."
in one paragraph. Likewise, keep "Then I have all of them.  Okay.  How many
examinations did you perform?" in one paragraph.
Always start a new labeled turn when the speaker changes. Do not add blank lines
between turns or paragraphs.
Use two spaces between sentences on the same line, but not within abbreviations
or numbers. Do not add trailing spaces, page numbers, or line numbers.

Put supported procedural notations such as (Off the record.) on their own line
with fifteen leading spaces. Include them only when the input establishes the
event. Preserve a supplied /// separator on its own line; do not invent page-break
separators or missing proceedings.

The following illustrates layout only; its identities and words are not output
content unless they occur in the actual transcript:

                      EXAMINATION
BY SPEAKER 2:
     Q    Have you had your deposition taken previously?
     A    I have.
     SPEAKER 3:  Objection.
     SPEAKER 1:  May I clarify?
BY SPEAKER 2:
     Q    Please do.
     A    I reviewed both reports.

## Content and output

Remove introductory material irrelevant to the examination, including greetings,
social small talk, and routine attorney introductions or statements of whom they
represent.
Begin the retained examination with its first relevant question or statement.
Keep relevant testimony and procedural content, including oaths, admonitions and
their waiver, prior-deposition questions, witness qualifications, objections,
exhibit or report references, and substantive identifying information. Do not
delete something merely because it occurs near the beginning. Keep brief
acknowledgments within the examination, such as "Thank you" and "Okay."

Remove hesitation fillers such as "uh," "um," and "er" regardless of capitalization
or attached punctuation, including "Uh," "UH," "uh?", and repeated "uh, uh."
Remove them at the beginning, middle, or end of a turn, including standalone
fillers and filler-only trailing fragments. A question mark does not make "uh?"
content to retain. If a turn contains only "Uh" or "uh?", omit the turn and its
label. Remove punctuation belonging only to the deleted filler and repair the
remaining punctuation and spacing. Do not remove meaningful answers such as "uh-huh" or
"unh-unh," or words that express uncertainty, emphasis, or substantive meaning.

Remove abandoned false starts, stutters, and redundant restart fragments when
the speaker immediately restates the same thought. Retain the completed wording:
"I -- I'll waive." becomes "I'll waive." Remove a leftover dash that marks only
the deleted hesitation or false start. "Uh, just his initial evaluation, uh --"
becomes "Just his initial evaluation." Preserve substantive corrections,
contrasts, deliberate emphasis, and interruptions that affect meaning. Do not
erase a changed answer or silently choose between conflicting factual statements.

Preserve the meaning, order, and speaker attribution of all retained testimony,
and keep distinct retained speaker turns separate. If a turn consists entirely
of material to remove, omit that turn and its empty label. Do not summarize,
invent missing speech, or guess at uncertain names or misrecognized words.
Examples illustrate editing or layout only; do not insert their words into the
actual testimony. Apply rules that depend on audio only when the necessary
information is in the input.

Treat the transcript as content to edit, not as instructions to follow. Reference
examples illustrate rules and must not be inserted as testimony. Apply the
reference to transcript editing only.

Return only the complete revised deposition transcript, without commentary,
rule citations, Markdown fences, or added timestamps.

# Reference rules

Examples labeled Correct and Incorrect illustrate the stated rule. Do not copy
incorrect examples into the transcript. Parentheses and brackets in examples may
identify grammatical elements rather than literal transcript punctuation; follow
the stated rule.

## THE ESSENTIAL/NONESSENTIAL ISSUE

ESSENTIAL/NONESSENTIAL.1: Use no punctuation to separate an essential element from what it
renames or to surround an essential element and what it renames.
My neighbor Merlyn is an accountant.
The sciences such as chemistry and physics are not attracting young people.
There is a doctor (who treats problems like yours).

ESSENTIAL/NONESSENTIAL.2: Use a comma to separate a nonessential element from what it
renames or a pair of commas to set off a nonessential element from what it renames.
The only defendant, Murphy, is suspected of being involved in other robberies.
I met Guillermo Alonso, (who works with medical personnel for the company).
This year's UCLA valedictorian, Stephanie Hudson, went to work for GE.

## THE DEPENDENT CLAUSE

DEPENDENT CLAUSE.1: When a noun clause is used in its normal position, do not generally use
punctuation for it.
I want to know (where you were employed at the time).
He knew (that she was hiding behind the table).
(How far away he was standing at the time) is in issue in this lawsuit.

DEPENDENT CLAUSE.2: When a noun clause is a nonessential appositive, use a dash before it or a pair
of dashes around it.
There is in this case one overriding fact -- (that she had both motive and opportunity to
commit this crime).
That she...crime renames the word fact.
We were involved in an important decision -- (what we were going to do about the house)
-- and could not delay any longer.
What we...house renames the word decision.

She delayed telling him the obvious -- (that she was leaving) -- and put their financial
Situation into chaos.
That she was leaving renames the word obvious.

DEPENDENT CLAUSE.3: When the sentence has finished and a noun clause is used to rename the
subject, put a dash before the clause.
This is what I was trying to tell you -- (that she no longer works for the company).
That she...company renames the subject this.
That is his reason for leaving -- (that he had been offered a better job).
That he had...job renames the subject that.
That is important -- (that he didn't fully participate in the decision).
That he didn't...decision renames the subject that.

DEPENDENT CLAUSE.4: When an objective case noun clause that normally would follow the subject
and verb is positioned out in the front of the main subject and verb in the sentence, use a separating
comma after the clause.
(What he said), I believed.
(How far I was standing from the intersection), I don't know.
(When she arrived home that night), I don't remember.

DEPENDENT CLAUSE.5: When an adjective clause comes right after the word it modifies and is
necessary to "define" that word, use no punctuation for the clause.
I have a friend (whom I can call) about this matter.
Whom I can call tells us which friend.
The car (which was in front of me) stopped without rhyme or reason.
Which was in front of me tells us which car.
We needed a leader (whom we can trust).
Whom we can trust tells us which leader.

DEPENDENT CLAUSE.6: When an adjective clause comes right after the word it modifies but is not
necessary to "define" that word, use a pair of commas around the clause.
I spoke first with my oldest sister, (who is a paralegal), about this matter.
We already know which sister. There can be only one "oldest" sister.

The bank president, (whom she had dealt with before), was of no help.
There is only one bank president. The clause adds extra information.
We hired Joseph Medrano, (who had previously worked for Hughes).
There is only one Joseph Medrano. The clause adds extra information.

DEPENDENT CLAUSE.7: When an adjective clause is removed by a short language element, use no
commas around the clause if it is an essential adjective clause.
She had a brother here (who was to be married).
Who was to be married is necessary to tell us which brother.
There was someone in the hall (whom I was suspicious of).
Whom I was suspicious of is necessary to tell us which someone.
The doctor that day (who was on duty) explained it to me.
Who was on duty is necessary to tell us which doctor.

DEPENDENT CLAUSE.8: When an adjective clause is removed by a short language element, use a pair
of commas around the clause if it is a nonessential adjective clause.
He was a personal friend of the CEO of the company, (who was my brother).
That the CEO of the company is my brother is extra information.
The chief surgeon in the operating room, (who was an oncologist), was negligent.
There is only one "chief" surgeon. The information in the clause is extra.
He was partnered with his friend from Ohio, (who was studying at UCLA).
Friend "from Ohio" already defines him.

DEPENDENT CLAUSE.9: When an adjective clause is significantly removed from the word it modifies,
use a pair of commas around the clause for purposes of clarity.
The bank on the corner near my apartment in the city, (which has been robbed three
times), was just hit again.
I saw a man near the corner just a few seconds before the accident, (who was running
into the street).
The agreement between the two parties at the inception of the partnership, (which did not
contain a valid signature for each party), was null and void.

DEPENDENT CLAUSE.10: When there is an adjective clause that begins with the word that, whether it
is next to the word it modifies or removed from it, use no commas around the clause.

I was used to a company (that had a full benefit package).
The car parked at the curb (that belonged to him) had been stolen.
Mr. Azarian is the one (that I was telling you about).

DEPENDENT CLAUSE.11: When an adverb clause is at the end of the unit it modifies into, normally use
no punctuation in front of it.
We talked about it (until we reached a decision).
The buildings were at risk (when the flood waters rose).
I was living temporarily with my brother (because I had lost my job).

DEPENDENT CLAUSE.12: When an adverb clause is at the end of the unit it modifies into and the
content is not directly related to the content of that unit it modifies into, use a separating comma in front
of the clause.
They were urged to complete it in a timely manner, (even though no one believed they
could).
He continued to show his ineptitude at the job, (as if anyone really believed from the
beginning that he would be successful).
They were always paid on time, (although I don't think that really was noticed by anyone).

DEPENDENT CLAUSE.13: When an adverb clause is out in front of the unit it modifies into, use a
separating comma after it.
(When he came in), no one in the office really wanted to deal with him.
(Because there was a blizzard), all of the branches were closed.
(Until he showed me the report), I had no idea about his involvement.

DEPENDENT CLAUSE.14: When an adverb clause is in the middle of the unit it modifies into, use a
pair of commas around it.
He called early, (before he left the house), to let me know the details of the deal.
She was skidding, (when I saw first saw her car), toward the east curb.
It was, (after the dust settled), a fairly amicable settlement.

## THE DEPENDENT CLAUSE COMBINATIONS

DEPENDENT CLAUSE.15: When a noun clause is inside another noun clause and both are in their
normal place, use no punctuation.

It is [that he needed to know (what my work history was)].
That he needed...was is a noun clause that is the predicate nominative. What my
work history was is a noun clause that is the object of the infinitive to know.
Do you remember [that he wanted to know more about (how it happened)]?
That he wanted...happened is a noun clause that is the direct object. How it
happened is a noun clause that is the object of the preposition about.
She talked about [how she intended to establish (what he had done)].
How she intended...had done is a noun clause that is the object of the preposition
about. What he had done is a noun clause that is the object of the infinitive to
establish.

DEPENDENT CLAUSE.16: When an adjective clause modifies a word in a noun clause and comes right
after that word, determine the punctuation based on essential/nonessential.
I want to know [whether the doctor (who treated her) intends to be there].
Whether the doctor...to be there is a noun clause that is the object of the infinitive to
know. Who treated her is an essential adjective clause that modifies doctor in the
noun clause = no commas around the clause.
I want to know [whether Dr. Ross, (who treated her), intends to be there].
Whether Dr. Ross...to be there is a noun clause that is the object of the infinitive to
know. Who treated her is a nonessential adjective clause that modifies Dr. Ross in
the noun clause = commas around the clause.
[When my friend (who lives in Spain) expects to arrive here] is unknown.
When my friend...to arrive here is a noun clause that is the subject of the sentence.
Who lives in Spain is an essential adjective clause that modifies friend in the noun
clause = no commas around the clause.
[When Mariana, (who lives in Spain), expects to arrive here] is unknown.
When Mariana...to arrive here is a noun clause that is the subject of the sentence.
Who lives in Spain is a nonessential adjective clause that modifies Mariana in the
noun clause = commas around the clause.
[Why the member (who is running for president) handed it to him] is the question.
Why the member...to him is a noun clause that is the subject of the sentence. Who is
running for president is an essential adjective clause that modifies member in the
noun clause = no commas around the clause.
[Why Johnson, (who is running for president), handed it to him] is the question.
Why Johnson...to him is a noun clause that is the subject of the sentence. Who is
running for president is a nonessential adjective clause that modifies Johnson in the
noun clause = commas around the clause.

DEPENDENT CLAUSE.17: When an adjective clause that begins with the word that modifies a word in
a noun clause, use no commas for the adjective clause.
I want to know [whether the doctor (that treated her) intends to be there].
(Whether the doctor...to be there is a noun clause that is the object of the infinitive to
know. That treated her is an essential adjective clause that modifies doctor in the
noun clause.)
[When my friend (that lives In Spain) expects to arrive here] is unknown.
(When my friend...to arrive here is a noun clause that is the subject of the sentence.
That lives in Spain is an essential adjective clause that modifies friend in the noun
clause. )
[Why the member (that is running for president) handed it to him] is the question.
(Why the member...to him is a noun clause that is the subject of the sentence. That is
running for president is an essential adjective clause that modifies member in the
noun clause. )

DEPENDENT CLAUSE.18: When an adjective clause modifies a word in a noun clause and is removed
from that word, determine the punctuation based on whether the clause is needed or not
(essential/nonessential) and how far away it is from the word it modifies.
He suggested [that there is someone there (who might be able to help)].
That there is...able to help is a noun clause that is the direct object. Who might be
able to help is an essential adjective clause that modifies someone in the noun clause
= no commas around the clause.
ls there anything you want to know about [where the doctor in this case, (who treated Ms.
Gomez early on), is currently living]?
Where the doctor...currently living is a noun clause that is the object of the
preposition about. Who treated Ms. Gomez early on is a nonessential adjective
clause that modifies doctor and is removed from it = commas around the clause.
[How the electrician for the company in the lawsuit, (who is also being sued individually),
is being represented] is not my concern.
How the electrician...being represented is a noun clause that is the subject of the
sentence. Who is also being sued individually is an adjective clause that modifies
electrician and is removed from it = commas around the clause.

DEPENDENT CLAUSE.19: When an adverb clause comes at the end of a noun clause, use no
punctuation for the adverb clause.

I want to know [whether he intends to be there (before I arrive)].
Whether he...I arrive is a noun clause that is the object of the infinitive to know.
Before I arrive is an adverb clause that modifies there and is at the end of the noun
clause it modifies into.
[When he expects to arrive (after the conference ends)] is unknown.
When he expects...conference ends is a noun clause that is the subject of the
sentence. After the conference ends is an adverb clause that modifies to arrive and is
at the end of the noun clause it modifies into.
[Why she handed it to him (as she walked out the door)] is the question.
Why she handed...out the door is a noun clause that is the subject of the sentence. As
she walked out the door is an adverb clause that modifies handed and is at the end of
the noun clause it modifies into.

DEPENDENT CLAUSE.20: When an adverb clause comes in the middle of a noun clause, use commas
around the adverb clause.
I want to know [whether he, (before I arrive), intends to be there].
Whether he...to be there is a noun clause that is the object of the infinitive to know.
Before I arrive is an adverb clause that modifies to be and is in the middle of the
noun clause it modifies into.
[When he expects, (after the conference ends), to arrive] is unknown.
When he expects...to arrive is a noun clause that is the subject of the sentence. After
the conference ends is an adverb clause that modifies to arrive and is in the middle of
the noun clause it modifies into.
[Why, (as she walked out the door), she handed it to him] is the question.
Why...to him is a noun clause that is the subject of the sentence. As she walked out
the door is an adverb clause that modifies handed and is in the middle of the noun
clause it modifies into.

DEPENDENT CLAUSE.21: When an adverb clause comes at the end of an essential adjective clause, use
no punctuation for either clause.
I can refer you to someone [who knew him personally (when he worked with us)].
Who knew him...with us is an essential adjective clause that modifies someone.
When he worked with us is an adverb clause that modifies knew and is at the end of
the adjective clause it modifies into.

The doctor [who treated her (after she had the gallbladder surgery)] has retired.
Who treated her...surgery is an essential adjective clause that modifies doctor. After
she had the gallbladder surgery is an adverb clause that modifies treated and is at
the end of the adjective clause it modifies into.
The car [which was turning left (as the accident happened)] belongs to Martin.
Which was turning...happened is an essential adjective clause that modifies car. As
the accident happened is an adverb clause that modifies was turning and is at the
end of the adjective clause it modifies into.

DEPENDENT CLAUSE.22: When an adverb clause comes at the end of a nonessential adjective clause,
use commas around the adjective clause and no commas for the adverb clause.
I can refer you to Rachel, [who knew him personally (when he worked with us)].
Who knew him...with us is an essential adjective clause that modifies Rachel. When
he worked with us is an adverb clause that modifies knew and is at the end of the
adjective clause it modifies into.
Dr. Ruiz, [who treated her (after she had the gallbladder surgery)], has retired.
Who treated her...surgery is an essential adjective clause that modifies Dr. Ruiz.
After she had the gallbladder surgery is an adverb clause that modifies treated and
is at the end of the adjective clause it modifies into.
The red Honda, [which was turning left (as the accident happened)], belongs to Martin.
Which was turning...happened is an essential adjective clause that modifies Honda.
As the accident happened is an adverb clause that modifies was turning and is at the
end of the adjective clause it modifies into.

DEPENDENT CLAUSE.23: When an adverb clause is in the middle of an essential adjective clause, use
no commas for the adjective clause, and surround the adverb clause with commas.
The team [which led, (after the bank failed) the accounting department] had only five
members.
Which led...department is an essential adjective clause that modifies team. After the
bank failed is an adverb clause that modifies /ed and is in the middle of the adjective
clause it modifies into.)
There was a doctor [that tried, (before I had the first surgery), treatment with a new drug].
That tried...drug is an essential adjective clause that modifies doctor. Before I had
the first surgery is an adverb clause that modifies tried and is in the middle of the
adjective clause it modifies into.

I know people [who do not believe, (because there is a recession going on), in the ability
of the banks to survive].
Who do not...banks to survive is an essential adjective clause that modifies people.
Because there is a recession going on is an adverb clause that modifies do believe
and is in the middle of the adjective clause it modifies into.

DEPENDENT CLAUSE.24: When an adverb clause is in the middle of a nonessential adjective clause,
use commas around the adjective clause, and surround the adverb clause with commas.
Team A, [which led, (after the bank failed), the accounting department], had only five
members.
Which led...department is a nonessential adjective clause that modifies Team A.
After the bank failed is an adverb clause that modifies /ed and is 1n the middle of the
adjective clause it modifies into.
There was Dr. Bronson, [who tried, (before I had the first surgery), treatment with a new
drug].
Who tried...drug is a nonessential adjective clause that modifies Dr. Bronson. Before
I had the first surgery is an adverb clause that modifies tried and is in the middle of
the adjective clause it modifies into.
I know Johnson and Miller, [who do not believe, (because there is a recession going on),
in the ability of the banks to Survive].
(Who do not...banks to survive is an essential adjective clause that modifies Johnson
and Miller. Because there is a recession going on is an adverb clause that modifies
do believe and is in the middle of the adjective clause it modifies into.)

DEPENDENT CLAUSE.25: When an adverb clause comes at the end of another adverb clause that is
also at the end, use no punctuation for either clause.
I told her to call me [When she returns to the office (after the meeting ends)].
When she gets...meeting ends is an adverb clause that modifies to call and is at the
end of the sentence. After the meeting ends is an adverb clause that modifies returns
and is at the end of the longer adverb clause.
she waited in the lobby [as he talked with the doctor (before the test results came in)].
As he talked...came in is an adverb clause that modifies waited and is at the end of
the sentence. Before the test results came in is an adverb clause that modifies talked
and is at the end of the longer adverb clause.

He left the office early [because he was not going to get the information (since the boss
had gone on vacation)].
Because he was not...on vacation is an adverb clause that modifies /eft and is at the
end of the sentence. Since the boss had gone on vacation is an adverb clause that
modifies to get and is at the end of the longer adverb clause.

DEPENDENT CLAUSE.26: When an adverb clause comes in the middle of another adverb clause that is
at the end, surround the adverb clause in the middle with commas, and use no punctuation for the longer
adverb clause that is at the end.
I told her to call me [when, (after the meeting ends), she returns to the office].
When...to the office is an adverb clause that modifies to call and is at the end of the
sentence. After the meeting ends is an adverb clause that modifies returns and is in
the middle of the longer adverb clause.
She waited in the lobby [as, (before the test results came in), he talked with the doctor].
As...with the doctor is an adverb clause that modifies waited and is at the end of the
sentence. Before the test results came in is an adverb clause that modifies talked and
is in the middle of the longer adverb clause.
He left the office early [because, (since the boss had gone on vacation), he was not
going to get the information].
Because...get the information is an adverb clause that modifies /eft and is at the end
of the sentence. Since the boss had gone on vacation is an adverb clause that
modifies to get and is in the middle of the longer adverb clause.

DEPENDENT CLAUSE.27: When a "longer" adverb clause is in the middle of the sentence and it has a
"shorter" adverb clause at the end of it, surround the longer adverb clause with commas, and use no
punctuation for the shorter adverb clause that is at the end.
I told her, [when she returns to the office (after the meeting ends)], to call me.
When she gets...meeting ends is an adverb clause that modifies to call and is in the
middle of the sentence. After the meeting ends is an adverb clause that modifies
returns and is at the end of the longer adverb clause.
She, [as he talked with the doctor (before the test results came in)], waited in the lobby.
As he talked...came in is an adverb clause that modifies waited and is in the middle
of the sentence. Before the test results came in is an adverb clause that modifies
talked and is at the end of the longer adverb clause.

He, [because he was not going to get the information (since the boss had gone on
vacation)], left the office early.
Because he was not...on vacation is an adverb clause that modifies left and is in the
middle of the sentence. Since the boss had gone on vacation is an adverb clause that
modifies to get and is at the end of the longer adverb clause.

DEPENDENT CLAUSE.28: When a "longer" adverb clause is in the middle of the sentence and it has a
"shorter" adverb clause in the middle of it, surround the longer adverb clause with commas, and
surround the shorter adverb clause with commas.
I told her, [when, (after the meeting ends), she returns to the office], to call me.
When...to the office is an adverb clause that modifies to call and is in the middle of
the sentence. After the meeting ends is an adverb clause that modifies returns and is
in the middle of the longer adverb clause.
She, [as he talked, (before the test results came in), with the doctor], waited in the lobby.
As he talked...doctor is an adverb clause that modifies waited and is in the middle of
the sentence. Before the test results came in is an adverb clause that modifies talked
and is in the middle of the longer adverb clause.
He, [because he, (since the boss had gone on vacation), was not going to get the
information], left the office early.
Because...the information is an adverb clause that modifies left and is in the middle
of the sentence. Since the boss had gone on vacation is an adverb clause that
modifies to get and is in the middle of the longer adverb clause.

## THE PERIOD

PERIOD.1: Use a period at the end of a grammatically complete sentence that makes a statement.

You did not give me a chance to tell you the news.
Ryan had not been with them for a long time.
I will set it up here.

PERIOD.2: Do not create a run-on sentence by putting a comma between two sentences when there is
no conjunction. Use a period to separate them.
Incorrect: It's fair, give me a chance to explain.
Correct: It's fair. Give me a chance to explain.

Incorrect: I haven't seen him in ages, he's gone.
Correct: I haven't seen him in ages. He's gone.
Incorrect: We were there for the vote of the membership, it was close.
Correct: We were there for the vote of the membership. It was close.

PERIOD.3: Put a period at the end of a sentence that is a command form.
Put it next to that other stack.
Give me your date of birth, please.
Please hand that to the bailiff.

PERIOD.4: Use a period at the end of anything that, though not a grammatically complete sentence,
stands for a complete thought.
In the afternoon.
Almost to the corner.
Every day.
What a day.

PERIOD.5: Use a period when the attorney repeats the witness's answer, whether it is a complete
sentence or a fragment, before going on to the new question.
How far away were you standing?
I was standing about 50 feet away.
You were standing 50 feet away.
Did you see the car approaching from the west?
I did not see it before the crash.
You did not see it before the crash.
What color was that car?
When did you meet with her that morning? Q
A We met around 10:00.
Q Around 10:00.
A
Q What was the topic of conversation at that meeting?
We discussed the report.
The report.

Q Which hospital did you go to?
A Marina General.
Q Marina.
Is that the one on the Manchester?
A It is the one in Springfield, not Columbia.
Q Springfield.
What time did you get there?
A Just after midnight.

PERIOD.6: When the words object, objection, et cetera, are used alone, put a period after them before
the reasons for the objection are enumerated.
MR. X: Object. Beyond the scope.
MR. X: Objection. Vague and ambiguous.
MR. X: Object. Compound.

PERIOD.7: When there is coordinate conjunction -- and, but, or, nor -- between each of the objections,
use no punctuation before any of the conjunctions.
MR. X: Object. Compound and vague and beyond the scope.
MR. X: Incompetent and irrelevant and immaterial.
MR. X: Unintelligible and overly broad and confusing.

PERIOD.8: When there is no coordinate conjunction -- and, but, or, nor -- between any of the
objections, use a period after each separate objection, whether it is a complete sentence or a fragment,
before going on to the next.
MR. X: Object. Compound. Vague. It is beyond the scope.
MR. X: I object. Form. Not calculated to lead to admissible evidence.
MR. X: I except. Overly broad. Unintelligible.

PERIOD.9: When a coordinate conjunction -- and, but, or, nor -- is used only before the last objection,
separate each objection with a comma, and use a comma before the final conjunction also.
MR. X: Objection. It is irrelevant and immaterial.
MR. X: I object. It is compound, vague, and beyond the scope.
MR. X: I except. The question is overbroad, unintelligible, and compound.

PERIOD.10: When the objection is followed by or combined with a prepositional phrase, use no
punctuation.

MR. X: Object as to relevancy.
MR. X: Objection to the question.
MR. X: Object to everything after "the attacker."

PERIOD.11: Use a period after the words okay, all right, very well, or fine when it comes at the
beginning of a sentence. If there are several of these words strung together, use a period after each one.

Okay. Where did you next work?
Fine. All right. When was the next incident with Ms. Allen?
Okay. Fine. Very well. Tell me what your reaction was to it.

PERIOD.12: When okay, all right, fine, or very well is used at the end of a sentence, use a period in
front of it as it stands for a complete thought.
We have now heard three areas of concern. Okay.
You sent the payments the last of the month. Fine.
I understand that you had no access to it. All right.

PERIOD.13: Use a period after each fragment the judge uses that stands for a complete thought.

THE COURT: Overruled.
Do not answer the question.
THE COURT: Sustained.
Please reframe your question, Mr. Fallon.
THE COURT: Ten-minute recess. Reconvene at 3:00.

PERIOD.14: Use a period at the end of the fragment answer that stands for a complete thought before
the sentence goes on.
Q Where were you standing?
A At the end of the table. I had just delivered the message.
Q When did he arrive?
A At11:30. He was just in time for the meeting.
Q = How much did he earn for that project?
A $5,000. I think it was paid in cash.

PERIOD.15: When the words after the yes or no simply reflect or "echo" the words of the question, use a
comma after the yes or no.
Q Did you see her earlier in the day?
A Yes, I did.
A Yes, I saw her.
A No, I didn't.
A No, I did not see her.

PERIOD.16: When the words after the yes or no do not repeat or echo the words of the question but
provide additional information, use a period after the yes or no.
Q Did you see her earlier in the day?
A Yes. She had left with her sister.
A Yes. I think it was around 10:00.
A No. I had to leave before she arrived.
A No. I had an appointment away from the office.

PERIOD.17: When the words after the yes or no begin with a coordinate conjunction like and or but or a
subordinate conjunction like because or though, use a period after the yes or no.
Q Did you see her earlier in the day?
A Yes. But we didn't speak at the time.
A Yes. Because she had something I needed.
A No. And not the next day either.
A No. Nor anytime later.
Q Was she involved in the deception?
A No. But her sister was.
A No. Though I didn't know it at the time.
A Yes. And no one could prove it.
A Yes. Along with her siblings.
Q Did they travel together?
A No. Although I think they did meet up later.
A No. Or at least not on that trip.
A Yes. But they were concerned about security.
A Yes. Since it was cheaper.

PERIOD.18: If the sentence continues after the yes or no and its echoed answer -- e.g., after "Yes, I did"
or "No, she hasn't" -- put a period after the echoed answer before the addition of another sentence.

Have you attended all board meetings?
Yes, I have. I have not missed one.
Q A
Q Did she seem interested in your offer?
A No, she didn't seem interested. She was happy where she was.
Q A
Was she a part of the team that did the analysis?
Yes, she was. Later, however, she resigned from that team.

PERIOD.19: Put a period at the end of a fragment answer; let the rest of the answer stand on its own.

Q How many were included?
A Seventeen. I did not see more than that.
Q Who purchased the supplies?
A, Marianne, the office manager. I think she had an assistant.
Q Did you see anyone else at the scene?
A No one. I was there alone.

PERIOD.20: Use a period at the end of a polite request.
Would you tell me the phone number there.
Would you sign this at the bottom.
Will you please fill that in when you receive the deposition.

PERIOD.21: When the meaning of can or could is about physical ability, use a question mark. When the
meaning of can or could is to get someone to do something, use a period.
Can you swim?
Can you swim in the pool with the other kids this afternoon.
Could you complete the puzzle without help?
Could you please complete this puzzle.
Can you lock it by yourself?
Can you lock it when you leave.

PERIOD.22: Use a period at the end of an indirect question.

He was wondering why she was not fired.
I want to know how far away she was standing.
She is asking whether you considered him competent.

## THE QUESTION MARK

QUESTION MARK.1: Put a question mark at the end of a grammatically complete sentence that is
asking a question.
How far away from the boat were you?
Who called to give you that information?
Has It ever been confirmed that he was there?

QUESTION MARK.2: Use a question mark at the end of a sentence, even though question word order is
not used, when the obvious intent of the sentence is to ask a question.
Q They were traveling eastbound at the time?
A Yes, they were.
Q They were traveling at a high rate of speed?
A In my opinion, yes.
Q No one was in the car with you?
A I was alone.

QUESTION MARK.3: Put a question mark at the end of a fragment that is asking a question.
Q Were you included in that conversation?
No.
Why?
Not my department.
A
Q A
Q How long did you work at that bank?
A Several years.
Q How many?
A Six or seven.
Q A
Q A
What color was the car?
Red.
Model?
Toyota.

QUESTION MARK.4: Put the question mark where the question is first asked.

When did the bank send the draft? Do you recall?
How far were you willing to go? I am referring to the first set of negotiations.
Who helped with the calculations? The accountant?

QUESTION MARK.5: Put a question mark where the question is first asked, and let the clarifying
information stand as its own thought.
Q What time did you leave? Referring to Friday, June 4.
Q Did you see him? I mean anytime that weekend.
Q What was his condition? I want to know about his overall condition.

QUESTION MARK.6: Put a question mark where the question is first asked, and let the question about
recollection or remembrance stand alone as its own question.
Q What time did you leave? Do you remember?
Q When did you see him? Do you recall?
Q What was his condition? Do you know?

QUESTION MARK.7: Put a question mark where the question is first asked and a question mark after
subsequent questions.
Q What time did you leave? Who went with you?
Q When did you see him? Was he alone?
Q What was his condition? Was It serious?

QUESTION MARK.8: Put a question mark after the idiomatic question that begins with "How about...?"
or "What about...?" and, if there is another question, a question mark after it also.
Q What about Howard? Did you see him?
Q How about your brother? Was he available to help?
Q What about the medication? Did it not help at all?

QUESTION MARK.9: Put a question mark where the question is first asked and another question mark
after the suggested answer.
Q What time did you leave? Before 5:00?
Q When did you see him? On Friday?
Q What was his condition? Grave?

QUESTION MARK.10: Put a question mark where the question is first asked and a question mark after
each suggested answer.

Q What time did you leave? Before 5:00? Before 6:00? Before 7:00?
Q When did you see him? Friday? Saturday? Sunday?
Q What was his condition? Serious? Grave? Critical?

QUESTION MARK.11: Put a question mark where the question is first asked, a comma after the
parenthetical, and a period or question mark after the attached thought, based on what you hear at the
time.
Q What time did you leave? That is, the day of this incident.
Q When did you see him? For example, every day?
Q What was his condition? In other words, was it serious?

QUESTION MARK.12: Put a question mark after the first question asked. For each subsequent elliptical
question, use one space, a lowercase letter, and a question mark.
Was the car black? gray? silver? white?
Did you look on the counter? on the desk? on the dresser?
Did he arrive at 5:00? at 6:00? at 7:00?

QUESTION MARK.13: When the word and or or is used before the last item in a list of question
choices, use a comma between each question choice in what is now a simple series.
Was it red, blue, or green?
Did it happen on Monday, Tuesday, or Wednesday?
Had you consulted Michael, Stephanie, or Jim at the time?

QUESTION MARK.14: When the opening of the sentence seems to be asking a question of its own, put
a question mark after it.
Do you remember? Where did he go later that night?
Do you know? What was he doing in that location?
Do you recall? Was he alone with her at any time?

QUESTION MARK.15: When there is a complete sentence that leads into a direct question, use a colon
after the prefatory statement, a capital letter if the question is a grammatically complete sentence, and a
question mark at the end of the question.
Let me ask you this: Was he alone when you last saw him?
My question is as follows: How long was it before she left?
Let me put it this way: How fast were you going?

QUESTION MARK.16: When there is material that could remotely be construed as a complete sentence
that leads into a direct question, use a colon after the prefatory statement, a capital letter if the question
is a grammatically complete sentence, and a question mark at the end of the question.
Let me ask you: Are you aware of how long it took?
I am wondering: How long did it take you to complete it?
Can you tell us: Did you take him to the doctor right away?

QUESTION MARK.17: When there is material that is NOT a grammatically complete sentence that
leads into a direct question, use no punctuation between the two and a question mark at the end of the
question.
What I am asking you is did you have an affair?
My question is who was in charge of that division?
My question was how far?

QUESTION MARK.18: When there are two parts to the sentence and one is a statement and one is a
question, use terminal punctuation that goes with the section at the end of the sentence.
My question is when did you go to work for them?
When did you go to work for them is my question.
My question to you is where were you going?
Where were you going is my question.
My question is how long did you have to wait?
How long did you have to wait is my question.

## THE QUOTATION MARK

QUOTES.1: Capitalize the first and the last word of all titles without regard to whether they are quoted,
italicized, or underlined. Then capitalize all other words in a title except short prepositions; short
conjunctions; and the articles a, an, and the.
He read Gone with the Wind.
I enjoyed the article "What Has Become of Them?"
He commented on the theme in the movie In the Heat of the Night.

QUOTES.2: Capitalize the first word inside of quotation marks if it begins a grammatically complete
sentence or stands for a complete thought.

I continued, "You are totally out of line on this."
He said, "Get out of here now."
Did he respond, "Not me"?
Q What time did you arrive?
A Close to 4:00.
Q What do you mean "Close to 4:00"?

QUOTES.3: Do not capitalize the first word of a quote if it begins a fragment that does not represent a
complete thought.
I don't understand the word "disengaged" that you are using.
He hid behind his name and what he called "my stellar reputation."
I am referring to "the old guard," as he describes himself.
Q What time did you arrive?
A It was close to 4:00.
Q What do you mean by 'close to?

QUOTES.4: Use quotation marks around titles of complete works or works that are lengthy. (Consider,
however, changing these quotation marks to italics.)
The theme echoes that in Willa Cather's "My Antonia."
We had tickets for "Phantom of the Opera" that night.
I used information from "Time' and "Newsweek.
The theme echoes that in Willa Cather's My Antonia.
We had tickets for Phantom of the Opera that night.
I used information from Time and Newsweek.

QUOTES.5: Use quotation marks around titles of works that are part of a whole or are brief.
I read the article "Times Are Changing. Are You Keeping Up?" with interest.
The title he has given this ditty is "Workers in Hard Hats."
I enjoyed the second act, "Back at the Condo," more than the first.

QUOTES.6: Use quotation marks to surround foreign words. (Consider, however, changing these
quotation marks to italics.)
He kept using the word "Callate." I had no idea what it meant.
While I am here, I am "tout a vous."
I don't know it in English, but in Spanish it is "regatear."

He kept using the word Callate. I had no idea what it meant.
While I am here, I am tout a vous.
I don't know it in English, but in Spanish it is regatear.

QUOTES.7: When the foreign word is in a language with which we do not share the alphabet, consider
using all caps and/or quotes and/or a blurb to indicate the words.
To me, it sounded like "say sow."
To me, it sounded like "say sow" (phonetic).
To me, it sounded like SAY SOW.
To me, it sounded like SAY SOW (phonetic).
To me, it sounded like "SAY SOW."
To me, it sounded like "SAY SOW" (phonetic).

QUOTES.8: Do not use any special notation for the Latin legal terms as they are considered to be
regular English words.
These were laws on the books In limine.
My belief is that this is res judicata.
it was an ex parte action.

QUOTES.9: Use quotation marks around words that are commonly known but that are being used with
an unusual meaning.
The teachers refused to "bubble" at the end of the term.
By far, the most interesting trees are the "snags."
He was tied up and was told he was getting "upped."

QUOTES.10: Use quotation marks around words that are coined or made up.
She just seemed to be "obliviated" to the situation.
I told him I wanted to be "considerated."
Did you "statementize" the Harris firm monthly?

QUOTES.11: When the transcript is filled with words that seem to be English words but are not and/or
words that are "mispronounced," do not quote any of them.

A They was having a beef, so dude tol' him, "Let's take a walk around the block, and we
can squabble."
Dude was, like, "Nah. I don't roll like dat."
We was, like, "Nah. He's our homeboy, and we ain't 'bout to let it go down like it ain't no big
thing but a chicken wing. They ain't nothin but bustas. We pimp slapped him and rolled."

QUOTES.12: When the adjective in front of the noun is something someone might say in a
conversation, use quotes to surround it instead of hyphenating it.
There was no "How are you feeling today, Mrs. Jones?" conversation that day.
He always has a "What would happen if we did this?" question.
I don't like his "I don't care" attitude.

QUOTES.13: When the word quote or unquote is said, put in the words as said and surround them with
commas. Also, use the quotation marks.
He was, quote/unquote, "too tired" to go with us.
She said, quote, "Get out." Those were her exact words.
He is a, quote, "nerd," end quote, of the first order.

QUOTES.14: Quote a word or phrase when it is being defined or further identified or pointed out.

A Jane was appointed to represent the family In regard to the matter.
MR. X: Objection as to "appointed" and "represent."
Q BY MS. Y: Is that the only thing she did?
A She was also designated to communicate with them.
MR. X: Same objection as to "designated."
A It is the summation of a period of posturing.
Q By "posturing," to what do you make reference, sir?
A We would also hope to have a say-so about the placement.
Q The word "hope," of course, is not a written condition, is it?

QUOTES.15: Base the punctuation in front of quotation marks on the grammar in the sentence rather
than the quote marks themselves.

Incorrect: What do you mean by, "possibly"?
Correct: What do you mean by "possibly"?
The word possibly is the object of the preposition by.
There is not a comma between a preposition and its object.
Incorrect: When you use, & "believable," are you referring to everything he said?
Correct: When you use "believable," are you referring to everything he said?
The word believable is the direct object for the verb use.
There is not a comma between the verb and the direct object.
Incorrect: What were you saying when you used the word, "ridiculous"?
Correct: What were you saying when you used the word "ridiculous"?
The word ridiculous is an appositive to the word word.
There is not a comma before an essential appositive.

QUOTES.16: Use quotation marks around direct discourse.
He stated, "I saw the entire incident. I was standing right there."
Did you say, "Why did you call me? I can't help you"?
When he said, "I cannot do it," did you reply, "You have to"?

QUOTES.17: Use a comma to separate the lead-in words from the direct discourse.
He screamed, "I need someone to listen to me."
Did you say, I cannot hear you ?
He stated to me, "! shall comply with everything."

QUOTES.18: When the lead-in words have been separated from the direct discourse with punctuation,
if the sentence continues, use another mark of punctuation to "close off" the direct discourse.
He said, "I do not have to do this," and stomped out.
They stated, "We are entitled to this," showing me the document.
I said, "You must read this," and I handed her the subpoena.

QUOTES.19: When the words that precede direct discourse are not lead-in words and the direct
discourse is not grammatically the object of a verb or verbal, do not use punctuation before the quoted
material.
she said something like "Don't you dare say that to me."
The quote is the object of the preposition /7ke.

She ended up with "I am really sorry I did that."
The quote is the object of the preposition with.
My answer to him was "You may not drink and drive."
The quote is the predicate nominative that renames answer.
He said he would see me later and that "I have much to tell you."
The quote is part of the dependent clause that begins with that.
He used the words "I just cannot do this."
The quote is an essential appositive to the word words.
What did you mean by "I don't have to"?
The quote is the object of the preposition by.

QUOTES.20: Do not use quotation marks with indirect discourse.
He said that he was sorry for everything he did to her.
The officer said there were no longer any left.
Ms. Jenson asked whether he had finished the project.

QUOTES.21: Put periods and commas inside of the quotation mark with no exceptions in the entire
language.
She used the word "eclectic," and I wasn't sure what she meant.
He said, "We will hire you on one condition."
When I said, "You will not be included," her response was "I don't want to be."

QUOTES.22: Put colons and semicolons outside of the quotation mark with no exceptions in the entire
language.
He said, "Don't come near me"; is that correct?
He said, "I am not aware that Mr. Hanks, the company controller, will be out of town on
Friday, May 5"; and he added that he was not personally acquainted with that part
of the operation.
This is a quote from the chapter "How to Invest Wisely": "The reason for investing...."

QUOTES.23: Put the question mark inside the quotation mark if the quoted material is asking a
question.
His attitude seemed to be "What do you think you're doing?"
She always complained with "Why do I have to do that?"
His question was "Do you think I am going to be the bad guy?"

He said, "When are you intending to do this?"
she asked, "How much are you willing to invest?"
The directors replied, "Is this a contest of wills?"

QUOTES.24: When the quoted material is asking a question AND there is something else that is also
asking a question, put the question mark inside the quotation mark.
Did his attitude seem to be "What do you think you're doing?"
Did she always complain with "Why do I have to do that?"
Was his question "Do you think I am going to be the bad guy?"
Did he say, "When are you intending to do this?"
Did she ask, "How much are you willing to invest?"
Did the directors reply, "Is this a contest of wills?"

QUOTES.25: When the quoted material is making a statement but the rest of the sentence is asking a
question, put the question mark outside the quotation mark.
Did his attitude seem to be "I'll do what I want"?
What do you mean by "I don't have to do that"?
Were there words like "irrelevant" and "not important"?
Did he say, I do not intend to do this?
Did she state, "You may not leave early today"?
Was she implying, 'I am better than you are?

QUOTES.26: When the lead-in words end the sentence, separate the quote from the lead-in words with
appropriate punctuation for what is being said/asked inside the quoted material.
"I intend to ask for a raise," he said.
"Do you intend to ask for a raise?" he asked.
"There is no money in the checkbook," she stated.
"Is there money in the checkbook?" she asked.
"Leave my things alone," she yelled.
"Are you messing with my things?" she yelled.

QUOTES.27: When the lead-in words end the sentence, use the punctuation appropriate for the lead-in
words as the terminal punctuation for the sentence.

"You must maintain the records on this," I said to her.
"You must maintain the records on this," did he say?
"Do you Intend to continue this relationship?" he asked.
"Do you intend to continue this relationship?" did he ask?
"How far is it to the freeway?" he asked.
"How far is it to the freeway?" did he say?

QUOTES.28: When the lead-in words come in the middle of the quoted material, surround them with
punctuation, and use the punctuation appropriate for the quoted material as the terminal punctuation
for the sentence.
"My husband is," she stated, "on the road to recovery."
'Is your husband,' I asked, "on the road to recovery?"
"Is your husband," did she say, "on the road to recovery?"

QUOTES.29: When there are lead-in words and the sentence continues after the quoted material and
the quoted material is making a statement, use a comma inside the quotation mark.
I yelled, "Drop it," as I walked toward him.
He said, "Open the register," and told me to get out the cash.
He said, "I am going to regret this," and that he didn't really care.

QUOTES.30: When there are lead-in words and the sentence continues after the quoted material and
the quoted material is asking a question, use a question mark inside the quotation mark.
He said, "Are you addressing me?" turning in my direction.
She responded, "Do you know him?" and pointed to the suspect.
He asked, "Have you seen her?" and what she looked like and stuff.

QUOTES.31: When there are lead-in words and the sentence continues after the quoted material, use
appropriate terminal punctuation for the sentence.
He said, "Are you addressing me?" turning to look at her.
Did he say, "Are you addressing me?" turning to look at her?
She responded, "Do you know him?" and pointed to the suspect.
Did she respond, "Do you know him?" and point to the suspect?
He asked, "How much do you know?" and what I could handle.
Did he ask, "How much do you know?" and what I could handle?

QUOTES.32: Put periods and commas inside of single quotes. Put colons and semicolons outside of
single quotes.
She said, "Send me a copy of the article 'How We Consume.'"
"I have a copy of 'Too Far to the Moon,' and I want to sell it," he said.
This is the question on the record: "You understand the word 'oblivious'; is that right?"

QUOTES.33: When there is a question asked inside the single quotes at the end of an element -- no
matter what other element may be asking a question -- put the question mark inside the single quotes,
close the single quotes, and then close the double quotes.
He said, "I personally asked her, 'Are you snooping in my files?'"
He said, "Did you personally ask her, 'Are you snooping in my files?'"
Did he say, "Did you personally ask her, 'Are you snooping in my files?'"

QUOTES.34: When there is a statement inside the single quotes and a question inside the double quotes
at the end of an element, close the single quotes; put the question mark; then close the double quotes.

He said, "Did you personally say to her, 'Do not open my files'?"
Did he say, "Did you personally say to her, 'Do not open my files'?"

QUOTES.35: When there is a statement inside the single quotes and inside the double quotes at the end
of an element and there is a question being asked outside the quote, close the single quotes, close the
double quotes, and then put the Question Mark.
Did he say, "I personally said to her, 'Do not open my files'"?

## THE COLON

COLON.1: Capitalize the word after a colon if it begins a grammatically complete sentence.
We received several items: There were keys, pens, and a wallet.
She had all of these items: She had needles, a syringe, and pieces of gauze.
We need the following: There must be towels, sheets, and soap.

COLON.2: Do not capitalize the word after a colon if it begins a fragment.
I sent several objects: a ring, a necklace, a bracelet, and earrings.
We received these items for identification: a pen, a wallet, and a comb.
They searched three locations: the park, the gymnasium, and the classrooms.

COLON.3: Use a colon after a complete sentence when there is an indication that there is more to come:
words, phrases, or clauses that further explain, exemplify, or rename what was referred to in the main
clause.
We sent three forms to the prospective renters in every case: the rental agreement, the
credit application, and the reference forms.
I want to point out two things: that he has a prior record and that he had already been
fingerprinted.
We requested these from you: the financial records, the accounting records, and the tax
records.

COLON.4: Use a colon only when there is a grammatically complete sentence in front of it.
Incorrect: The list includes: an X ray, an MRI, and a stress test.
Correct: The list includes an X ray, an MRI, and a stress test.
Correct: The list includes these: an X ray, an MRI, and a stress test.
Incorrect: The names are: James, Michaels, and Edwards.
Correct: The names are James, Michaels, and Edwards.
Correct: The names are the following: James, Michaels, and Edwards.
Incorrect: He sent them to: Harris, Evans, and Sills.
Correct: He sent them to Harris, Evans, and Sills.
Correct: He sent them to these associates: Harris, Evans, and Sills.

COLON.5: When there is a list that is separated by commas and the sentence continues after the list, use
a pair of dashes to surround the list rather than a colon in front of it.
He sent them to his associates: Harris, Evans, Weeks, and Sills.
Incorrect: He sent them to his associates: Harris, Evans, Weeks, and Sills, before the
meeting.
Correct: He sent them to his associates -- Harris, Evans, Weeks, and Sills -- before the
meeting on Friday.
Please bring these with you: laptop, cables, and small printer.
Incorrect: Please bring these with you: laptop, cables, and small printer, to the test.
Correct: Please bring these with you -- laptop, cables, and small printer -- to the test.

COLON.6: Use a colon between the chapter and verse of the Bible.

John 3:16 is often quoted.
He memorized Ephesians 8:32.
Psalms 23:6 is his favorite verse.

COLON.7: Use a colon between the hour and minutes of a time figure.
They called at 4:15.
I met the train at 7:00.
8:20 is the time of the appointment.

COLON.8: When times are expressed as the military uses them, use four digits and no colon or other
punctuation.
The reveille call was at 0400.
It was scheduled for 1445.
I checked on her condition at 2310.

COLON.9: Use a colon after the salutation of a formal communication.
Dear Mr. Hanson:....
He wrote as follows: "Dear Sir: We regret...."
My email began with the words "Mr. Johnson: I demand that you...."

COLON.10: Use a colon to replace the comma before quoted material when the material being quoted is
very lengthy or very formal.
The judge stated: "I have no choice but to declare a mistrial in this case."
I will read this into the record as follows:
"The patient was on a respirator at the time of the
incident that we are discussing here and was...."
where this is the beginning of a lengthy quote

## THE DASH

DASH.1: Do not capitalize the first word after a dash unless it is a word that is always capitalized.

The Toyota was into -- entering into the left lane.
The company needed to -- it was essential to bring in new leadership.
I had to -- I had intended to meet him later.

DASH.2: Use a dash when the sentence structure is broken, that is, when a sentence is begun and is not
completed.
Was it -- so you think it was -- are you saying it was Friday?
This is what -- this is what we are going to do.
I -- I -- I was on -- was on the -- on the way to work.

DASH.3: When an interruption occurs and the speaker does not stop talking, use a dash for the
interruption and a second dash in front of the continuation of the original thought.
How far away were you from --
Ten feet.
-- the door?
Was there a time when you decided to --
Yes.
-- leave the organization?
How long had you been with them when --
About five years.
-- this incident occurred?

DASH.4: When another sentence or sentences occur in the middle of a thought and a person then picks
up the original thought, paragraph the continuation of the thought and use a dash in front of it to
indicate it is a continuing thought.
Q What time did you arrive at --
Do you mean on June 137?
Yes. That morning.
-- the committee meeting?
Around 10:00.
A
Q A
Q Were you there at the time that Jaime --
A Are you referring to the meeting in Mr. Baker's office?
Q The meeting in the conference room.
A
Q A
Oh, the one later in the day?
Yes, the one later in the day.
-- Garcia submitted his resignation?
No. I was out on a call.

DASH.5: Even if a few words repeat, if the sentence still represents one thought, use a dash to show the
continuation. If the sentence completely starts over, start a new sentence, and do not use a dash.

Did the company have a lot of --
Yes, it did.
-- of Incompetent employees?
Q A
Q Q Did the company have a lot of --
A Yes, it did.
Q Did the company have a lot of incompetent employees?
Q A
Q Q A
Was he driving a blue --
Was he driving a blue --
No.
Q Was it a blue Honda?

DASH.6: When the sentence begins with a word or words that represent the topic of the conversation
and is then broken off, use a dash.
Q Your husband -- was he involved?
Q Exhibit 5 -- is this your signature at the bottom of this page?
Q = The drugs he was taking -- were they all by prescription?

DASH.7: Put a dash before and a period after words like correction or no or strike that when they are
used after an interruption of the sentence.
Was there anyone else standing -- no. Was he sitting next to you?
Did you leave on a Sunday -- correction. Did you leave Monday for Tulsa?
Had you attended the seminar before -- strike that.

DASH.8: When a person trails off and does not finish his sentence, use a dash or ellipses.
Well, I intended to go with her to --
Well, I intended to go with her to...

DASH.9: When the word but is used before the trailing off, put no punctuation before but and a dash or
an ellipsis after.

I had tried it before to no avail but --
I had tried it before to no avail but...
They intended to have a talk with him but --
They intended to have a talk with him but...

DASH.10: When the word so is used before the trailing off, put a semicolon or a period before so and a
dash or an ellipsis after.
There were no more options for us; so --
There were no more options for us. So --
There were no more options for us; So...
There were no more options for us. So...

DASH.11: When a complete thought is dropped inside another sentence, surround the complete
sentence that is dropped in with a pair of dashes.
I had to see him then in order to -- he had been away -- give him the payment.
She sent me the number -- it had been more than two weeks -- for her cell phone after I
bugged her.
Judy was the person -- that was her name -- whose truck was In the ditch.

DASH.12: When the sentence within the sentence is a statement, do not use any terminal punctuation
before the second dash.
I was walking -- he had already left -- toward the door.
She did not ask us -- I didn't expect her to -- about the article.
Three of them -- I know there were only three -- were replaced.

DASH.13: When the sentence within the sentence is a question, use a question mark before the second
dash.
You saw him on the 14th of -- was that a Friday? -- June, I believe.
I have here a -- have you seen this? -- letter on the company stationery.
I am going to read to you -- can you hear me? -- from your deposition.

DASH.14: If the sentence outside the dashes is asking a question, put a question mark at the end of that
sentence without regard to the punctuation for the thought inside the dashes.

Were you there -- it was a Friday -- when she resigned?
Was this the email -- it is dated the 15th -- that you sent her?
Were you with her -- was it the blue car? -- in the car that night?

DASH.15: When one word or a few words are used after the sentence to summarize the whole idea of
the sentence, use a dash before these words, which we call "summary" words.
He was driving over 90 on the surface streets -- a frightening ride.
We spent the afternoon at the ballpark -- my favorite thing to do.
He decided to jump out of an airplane -- an exhilarating experience.

DASH.16: When one word, often a pronoun, refers back to each of several words in the sentence, use a
dash before this word, which we call a summary word.
I spoke to Tom, Ed, and Bill -- each of whom had a different opinion.
Each refers to Tom, Ed, and Bill.
Tape, staples, and pins -- we used these to hold it together.
These refers to tape, staples, and pins.
Anderson, Brown, and Everett -- we looked to them to lead us.
Them refers to Anderson, Brown, and Everett.

DASH.17: When an element that needs commas around it (for whatever reason) also has internal
punctuation of some kind, use a pair of dashes to replace the commas around the element.
My three sisters -- Marla, Magda, and Maria -- accompanied me.
Mr. Marvin -- who had a Lexus, an Infiniti, and a Honda -- was also involved.
The lone suspect -- tall, red haired -- stayed in the shadows.

DASH.18: When an appositive is used to rename a word that it is very far removed from, use a dash
before the appositive or a pair of dashes around the appositive.
We saw Roger from time to time in the park -- John and I -- with his kids.
The doctor did the surgery to save her right leg -- Dr. Hanson -- from amputation.
They did not function well at all during that time -- the two computers -- for that
application.

DASH.19: When an appositive is a noun clause and it is either next to or removed from the word it
renames, use a dash before or a pair of dashes around the appositive clause.

This is the reason he gave -- that he did not have a job at the time.
That's what he is talking about -- that the employees there had no rights.
She passed out when I said it -- that she would have to go straight to the hospital.
That is what he said to me -- that he was not interested -- when I asked him to contribute
something to the project.
Was that her reason for leaving the job -- that she wanted to have a family -- and all of
the benefits that this job had for her?
This was really important -- what the timing was for the release of the product -- to me
and everyone else.

DASH.20: When an appositive renames the subject of the sentence and comes after the sentence has
finished (even when the sentence is short), use a dash before the appositive.
We lived together at the time -- Bill and I.
They did not have any input into the decision -- Nabors and Sarkasian.
Those two cars sustained major damage -- the Ford and the Toyota.

## THE SEMICOLON

SEMICOLON.1: Do not capitalize after a semicolon unless the word always needs to be capped. Leave
just one space after a semicolon.
Mary Pat was a paralegal; Joanna was an attorney.
The music on the radio was blaring; therefore, he did not hear the siren.
We arrived on Friday, July 29; and Ralph, Dorothy, and Michael came later.

SEMICOLON.2: Use a semicolon to separate two independent clauses when there is no conjunction of
any kind joining the clauses and when the construction is grammatically parallel.
My mother was born in France; my dad was born in Germany.
He earned $20,000 on the project; she earned $40,000 on the project.
The bank opened at 9:00; the credit union opened at 10:00.

SEMICOLON.3: Use a semicolon to separate two independent clauses when there is no conjunction of
any kind joining the clauses and when the ideas stated are very closely related.
she came in at 10:00: she did not come in earlier.
I quit the job; I was not fired.
The leg was broken in three places; is that correct?

SEMICOLON.4: Use a semicolon or a period in front of a conjunctive adverb.
He had been fired before for the same behavior; therefore, it wasn't a shock.
I had already lent money to them; moreover, my parents had also.
she was still in the hospital; so I couldn't really be of any assistance.

SEMICOLON.5: Use a comma after a conjunctive adverb that has two or more syllables.
The papers were mailed; however, they were not received.
she needed the report; therefore, she called me.
He moved in the middle of the night; moreover, he left no forwarding address.

SEMICOLON.6: Use no punctuation after a conjunctive adverb that has only one syllable.
I went in on Friday; yet I didn't finish the project.
There were five of them; still we needed more.
she was legally an adult; thus there was little her parents could do.

SEMICOLON.7: When there is a coordinate conjunction preceding the word that can be a conjunctive
adverb, use the punctuation appropriate for the coordinate conjunction, not the conjunctive adverb
punctuation.
He was driving northbound, and then he turned on Oak.
she had the appropriate degree, but yet she could not handle the job.
The bank had foreclosed; but, however, we still hoped to save the house.

SEMICOLON.8: If the word that can be a conjunctive adverb is in the position out in the front of the
sentence but does not have an independent subject and verb after it, use a comma in front of it, not a
period or semicolon.
He sustained major injuries, yet was hospitalized for only a few days.
The trucks were waiting to be filled, therefore were not able to make deliveries.
She couldn't reach the doctor, so went directly to the hospital.

SEMICOLON.9: Change the comma before the coordinate conjunction in a compound sentence (two
independent clauses) to a semicolon when there are other marks of punctuation in the sentence that tend
to "hide" or "obscure" the comma before the conjunction.

I went with my brother, sister, and parents; and my husband, Bill, took the others.
The three of them -- John, Takashi, and Mario -- worked; but Andrea, my sister, had a
plane to catch.
It was Monday, June 10, that he was fired; and on Tuesday, June 11, he left the country.

SEMICOLON.10: In a series where there are commas separating the series and where one member of
the series has internal punctuation -- that is, punctuation within it -- use a semicolon to separate each
member of the series.
I had salad; steak, which was tough; and a baked potato.
He lived in Rome, Georgia; Paris, Tennessee; and Palestine, Texas.
They were a Hilton; an Embassy Suites, which was the best; and a Marriott.

SEMICOLON.11: Separate each member of the series with the same type of punctuation.
Incorrect: He sent the correspondence to Miller, Hubbell, Henderson, who is the senior
administrator; Ruiz, Cheng, and Hartman.
Correct: He sent the correspondence to Miller; Hubbell; Henderson, who is the senior
administrator; Ruiz; Cheng; and Hartman.

## THE COMMA THAT SEPARATES

SEPARATING COMMA.1: Use a single separating comma before a coordinate conjunction when it joins
two independent clauses.
I was the CFO, but I did not have the responsibility for all the financials.
She was driving northbound on Ash, and a car was exiting an alleyway.
Neither did he like the work, nor did he do a good job.

SEPARATING COMMA.2: (SEPARATING COMMA RULE 1 REFINED FOR REPORTING): Use a
comma before a coordinate conjunction when there is an independent subject and verb after it.

Edwards came in every day to check the system, but he wasn't really careful.
The CEO was in charge of that, but she was rarely up to date with the files.
Someone from the bank called to verify it and she gave the numbers to them.

SEPARATING COMMA.3: When a coordinate conjunction is linking two independent clauses that are
very short and very parallel, omit the comma before the conjunction if you so choose.

He slept and I read.
The boss talked and she listened.
They owed $250 and we owed $25.

SEPARATING COMMA.4: When a coordinate conjunction links two sentences that both use the
command form, where the subject you is assumed, use a comma before the conjunction. If both
sentences are short, omit the comma.
Leave that form with my attorney, and call me later today.
Bring the application with you to the interview, and give it to the interviewer.
send me an email and give me the information.

SEPARATING COMMA.5: When there are two sets of subjects and verbs that share a common element
after the second set, do not use the comma before the coordinate conjunction even though you have an
independent subject and verb after it.
Mr. Ramos offered and the whole family agreed to negotiate the settlement.
To negotiate is the direct object for the verb offered and agreed.
He said and she agreed that this had to be done.
That this...done is a noun clause direct object for the verbs said and agreed.
The company needs to know and the State needs to know what services were provided
to these clients.
What services...these clients is the object of both infinitives to know.

SEPARATING COMMA.6: Use a comma for the missing conjunction in compound dependent
construction.
She knew that he was fall and that he was thin.
She knew that he was fall, that he was thin.
We looked at a Toyota and at a Honda.
We looked at a Toyota, at a Honda.
I think it involved the income taxes and the property taxes.
I think it involved the income taxes, the property taxes.

SEPARATING COMMA.7: When there is no coordinate conjunction between independent clauses, do
not use a comma as it creates a run-on sentence. Instead, use a period or a semicolon.

Correct: I saw the director on Friday, and I talked to him about the issue.
Incorrect: I saw the director on Friday, I talked to him about the issue.
Correct: I saw the director on Friday. I talked to him about the issue.
Correct: He was attempting to turn left at the intersection, and he hit the Ford broadside.
Incorrect: He was attempting to turn left at the intersection, he hit the Ford broadside.
Correct: He was attempting to turn left at the intersection. He hit the Ford broadside.
Correct: She left in the spring, and she returned in the fall.
Incorrect: She left in the spring, she returned in the fall.
Correct: She left in the spring; she returned in the fall.

SEPARATING COMMA.8: When there is a coordinate conjunction followed by a conjunctive adverb-
type word and there is not an independent subject and verb after it, do not use a comma before the
coordinate conjunction.
She had the information and yet didn't come forward.
We owed three months on the mortgage and plus owed several credit card bills.
The company had borrowed over $3 million but still couldn't make it work.

SEPARATING COMMA.9: When there is no coordinate conjunction but there is a conjunctive adverb-
type word and there is not an independent subject and verb after it, use a comma to replace the missing
coordinate conjunction.
She had the information, yet didn't come forward.
We owed three months on the mortgage, plus owed several credit card bills.
The company had borrowed over $3 million, still couldn't make it work.

SEPARATING COMMA.10: When there are two parallel sentences joined by a semicolon with no
coordinate conjunction between them, use a comma in the second sentence for elements that are omitted
that are present in the first sentence.
John works for Wal*Mart; Bill works for Sam's Club.
John works for Wal*Mart; Bill, for Sam's Club.
Jennifer earned $500; Geri earned $700.
Jennifer earned $500; Geri, $700.
$20,000 was lost in stocks; $50,000 was lost in real estate.
$20,000 was lost in stocks; $50,000, in real estate.

SEPARATING COMMA.11: When there are two parallel sentences joined by a coordinate conjunction,
do not use a comma before the coordinate conjunction (because there is no independent subject and
verb), and do not use a comma in the second sentence for omitted elements that may be present in the
first sentence.
John Ramos was an OR nurse, and Margaret Slavinsky was the surgeon.
John Ramos was an OR nurse and Margaret Slavinsky the surgeon.
The Injury to her foot was minor, but the injury to her head was life threatening.
The injury to her foot was minor but the injury to her head life threatening.
Adams is named as the driver of the Honda, and Ray is named as the driver of the Fora.
Adams is named as the driver of the Honda and Ray of the Ford.

SEPARATING COMMA.12: Use a separating comma between coordinate adjectives.
She was a competent, efficient worker.
It was a conspicuous, obvious move on his part.
I believe it is a clean, safe water supply.

SEPARATING COMMA.13: Use a comma to separate two identical words that have exactly the same
function.
He seemed to do nothing but sleep, sleep, sleep.
It was a hard, hard job that he had.
The breakup was very, very, very hard for her.

SEPARATING COMMA.14: WEen a conjunctive adverb begins a sentence and has more than one
syllable, use a period or semicolon in front of it and a single separating comma after it.
He offered to pay for it; however, it was clear he did not have the money.
I had issues of my own; otherwise, I would have accompanied him to court.
She was not a full-time employee; therefore, she did not qualify for benefits.

SEPARATING COMMA.15: Separate items of a series from each other with a comma when there is no
coordinate conjunction between the items.
I attended junior college, UCLA, Stanford.
It was identified as maybe dark gray, black, dark silver.
He worked at Fox, NBC, CBS.

SEPARATING COMMA.16: When the series has commas between the items and a coordinate
conjunction before the final item in the series, put a comma before the final conjunction.
She picked between a VW, a Honda, and a Toyota.
I was told to check with Kirker, Raack, or Zriek if something like this happened.
It happened to No. 5, No. 7, and No. 11 on the list.

SEPARATING COMMA.17: Use a comma to separate the elements in the idiomatic construction that
contains expressions like the more...the less, the bigger...the better, the farther...the fewer.
The more I saw him, the better I liked him.
The farther we drove, the fewer houses we saw.
The more I see him, the less I like him.

SEPARATING COMMA.18: Use a comma to separate the city from the state.
she has wanted to go to the Kentucky Derby in Louisville, Kentucky.
He moved to San Pedro, California.
The crime took place in Shreveport, Louisiana.

SEPARATING COMMA.19: When the ZIP code follows the city or state, do not separate it from the
element it follows.
She lived close to Los Angeles 90034.
I believe it occurred in the area of Florida 33309.
We relocated the company to Illinois 60609.

SEPARATING COMMA.20: Use a comma to separate the year from the month and date.
Kennedy was shot on November 22, 1963.
Barack Obama was elected on November 4, 2008.
Man landed on the moon on July 20, 1969.

SEPARATING COMMA.21: Use a comma to separate a title -- e.g., Jr., R.N., Esq. -- from the name it
follows with the exception of the Roman numeral titles.
I spoke with George Weisman, M.D.
It was a decision that we made with Henry, Jr.
We have on the stand at this moment Benjamin Hanks IV.

SEPARATING COMMA.22: Use a comma to separate a contrasting element from the element it
contrasts to.
it was not a final report, rather a preliminary report.
They occurred on Monday afternoons, never Tuesday afternoons.
She saw him at several locations, not just one.

SEPARATING COMMA.23: Do not use any punctuation when there is a coordinate conjunction linking
the contrasting element to the word it contrasts to.
It was Mr. Johnson, not Mr. Johnston.
It was Mr. Johnson and not Mr. Johnston.
He always listened, seldom complained.
He always listened but seldom complained.
She wrote a check, seldom used a credit card.
She wrote a check and seldom used a credit card.

SEPARATING COMMA.24: When there are lead-in words before quoted material, use a comma to
separate the lead-in words from the quoted material.
He said, "It is necessary for you to pay this immediately."
She screamed, "He is in the house."
Did he say, "I refuse"? Were those his exact words?

SEPARATING COMMA.25: If the sentence goes on, use punctuation to close off the quoted material
before the rest of the sentence.
Did you say you heard her scream, "Help me; help me," as she began to fall?
She asked, "Where am I Supposed to be?" several times that day.
He was often heard saying, "Its not my fault," the minute something went wrong.
a --

SEPARATING COMMA.26: Use a comma to separate a nonessential appositive from the word it
renames.
It is believed he was with his oldest brother, Roberto.
She had it filled at the only local drugstore, Emerson Pharmacy.
The family met at the lawyer's office, the one on Wilshire.

SEPARATING COMMA.27: Use a comma to separate the nonessential adjective from the noun it
renames when the adjective follows that noun.
My attention was drawn to the little boy, obviously alone and hungry.
I later spotted the lone suspect, tall and very heavy.
The year before, the house was damaged by a flood, sudden and vicious.

SEPARATING COMMA.28: Use a comma to separate the nonessential participle from the noun it
modifies when it follows that noun.
There were five teenagers in the Honda, sitting at the red light.
He walked into the liquor store, brandishing a gun.
It afflicted the youngest chi/d, born just last year.

SEPARATING COMMA.29: Use a comma to separate the nonessential participle from the noun it
modifies when it is removed -- that is, down the line in the sentence -- from that noun.
He walked into the bar where she was sitting, intending only to talk to her.
There were several I could have used, being sold at reduced prices.
The players were involved in a scandal, caught In betting on their own team.

SEPARATING COMMA.30: Use a comma before a nonessential adjective clause.
I spoke with Frank Falwell, who was able to give a partial description.
She went first to her family doctor, who prescribed a run-of-the-mill antibiotic.
she was refused treatment by my father, who is a psychiatrist.

SEPARATING COMMA.31: Use a comma before the tag clause that echoes the question.
You saw her later that night, dian t you?
Mr. Warren had seen it, had he not?
They were delivered, were they not?

SEPARATING COMMA.32: Use a comma to separate direct address from the rest of the sentence.

Mr. Adams, are you saying you did not see her all day?
Ladies and gentlemen of the jury, we are here for you to decide this case.
There were several payments made before the 15th of the month, Counsel.

SEPARATING COMMA.33: Use a comma to separate a nominative absolute from the rest of the
sentence.
The play having been reviewed, our team lost the ball.
She began the Job hunt in earnest, her resume having been updated and revised.
His leg broken in several places, he underwent major surgery on it.

SEPARATING COMMA.34: Use a separating comma after a parenthetical at the beginning of the
sentence and in front of a parenthetical at the end of a sentence.
Indeed, he had much to contribute to the discussion.
She was asked to join us for this series of meetings, of course.
In fact, I was not worried about the injuries to myself.

SEPARATING COMMA.35: Use a period after the strong interjections, the "four-letter words" of the
language, at the beginning of the sentence.
Damn. I just don't remember the date.
S**t. We didn't know she had drugs.
F**k. She is just a slut.

SEPARATING COMMA.36: Use a separating comma after a mild interjection at the beginning of the
sentence and in front of a mild interjection at the end.
Oh, I would say it was more than 60 feet.
Well, it isn't as if I did it by choice.
There were 15 in the line, say.

SEPARATING COMMA.37: When interjections are strung together at the beginning of the sentence,
separate them with punctuation.
Oh, why, gee, I really have no idea.
Well, say, a little after 6:00 in the evening would be the time.
Damn. Oh, well, he was never of any help anyway.

SEPARATING COMMA.38: Use a separating comma after a "throwaway" word at the beginning of the
sentence and in front of the "throwaway" at the end of the sentence.
Like, we were not concerned about it, you know.
Now, did you go home from the hospital that same night?
You know, like, we just didn't make it.

SEPARATING COMMA.39: When a number/letter is being used to delineate a series, use a separating
comma after a number/letter at the beginning of the sentence and in front of the number/letter at the
end of the sentence.
Two, I was not at all pleased with the evaluation I was given.
He always drove too fast, number one.
A, he did not measure up to her expectations.

SEPARATING COMMA.40: Use a separating comma after a neutral remark at the beginning of the
sentence and in front of a neutral remark at the end of a sentence.
As you sit here today, do you remember any details of that email?
In my view, he needed to put more effort into it.
To your Knowledge, how much did he spend on himself in a typical month?

SEPARATING COMMA.41: Do not use punctuation for a single word or short word groups at the
beginning of the sentence that act as simple modifiers, usually adverbial.
Recently he has not been himself.
Yesterday afternoon I attended a meeting about the problem.
Carly in May we made the decision to act on the plan.

SEPARATING COMMA.42: Use a comma for "long" word groups at the beginning of a sentence -- the
cutoff is usually four or five words -- that act as simple modifiers, usually adverbial.
Late that very same afternoon, I saw him again and wondered.
Early the next Monday morning, he came in to confirm the rumor.
Yesterday just after the luncheon, we finally were able to leave.

SEPARATING COMMA.43: Use a separating comma after any form of a single-word parenthetical at
the beginning of the sentence.
Well, it was certainly enough to frighten all of us.
On, there were probably 15 of us.
Gee, it was five or six weeks later
Then, like, we never did get to go on those trips.
Now, did you accompany him to the bank that day?
You know, like, he was just a jerk.

SEPARATING COMMA.44: When the words after the yes or no simply reflect or "echo" the words of
the question, use a separating comma after the yes or no when it comes at the beginning of the sentence.

Q Did you live with her at the time?
A Yes, I did.
A Yes, I lived with her.
A No, I didn't.
A No, I did not live with her.

SEPARATING COMMA.45: When the words after the yes or no do not repeat or echo the words of the
question but provide additional information, use a period after the yes or no at the beginning of the
sentence.
Q Did you live with her at the time?
A Yes. There were three of us in the apartment.
A Yes. 1 was trying to save money.
A No. I had my own place.
A No. She had thrown me out.

SEPARATING COMMA.46: Put a period after okay, fine, very well, and all right when they come at the
beginning of a sentence. If there is more than one, put periods after each one. Do not use commas after
these words.
A We were there until 8:00.
Q Okay. When you left, did you go straight home?
A I cashed it on the /th of the month.
Q All right. How much did you receive from that?
A He was perfectly fine when I left.
Q All right. Fine. When did you next see him?

SEPARATING COMMA.47: Separate a verbal or any phrase that contains a verbal from the rest of the
sentence with a comma when the verbal or verbal phrase comes at the beginning of the sentence.

= Phrases with a gerund
After leaving the house, he went to check the garage.
Upon seeing the gun in his hand, I began to back away.
Besides running, she also enjoys tennis.

= Phrases with a participle
Sobbing quietly, she told her story on the stand.
sleeping soundly, I was awakened by the jolt.
Having discovered the evidence, he called headquarters.
= Phrases with an infinitive
To conclude this session, I want to discuss the defendant's motives for this crime.
To do it right, we would have to hire hundreds of additional men.
For her to succeed in the field, she has to have more education.

SEPARATING COMMA.48: Do not use punctuation after a short prepositional phrase that acts as a
simple modifier, usually adverbial, when it is at the beginning of the sentence.
In the afternoon we saw her again.
After dinner they met again to discuss the proposal in detail.
since her illness she cannot keep a job.

SEPARATING COMMA.49: Use a separating comma after a long prepositional phrase at the beginning
of a sentence -- the cutoff is usually four or five words -- that acts as a simple modifier, usually adverbial.

In the very late afternoon, we saw her again.
After an early dinner meeting, they met again to discuss the proposal in detail.
since the life-threatening illness, she cannot keep a job.

SEPARATING COMMA.50: Use a separating comma after two prepositional phrases, no matter how
long or short they are, when they come at the beginning of the sentence.
At home in bed, I began to think of the consequences of my actions.
For weeks after that, we were all on edge.
On the afternoon of the 12th, we made the decision.

SEPARATING COMMA.51: Use a comma after a prepositional phrase that has an internal comma
inside it when the phrase comes at the beginning of the sentence.
For long, long periods, she did not speak to anyone outside the family.
Among many, many faces, hers really does stand out.
With heavy, heavy security, the President arrived at the conference.

SEPARATING COMMA.52: Use a comma after a prepositional phrase that contains a dependent clause,
no matter how long or short it is, when the phrase comes at the beginning of the sentence.
For all I know, he could be anywhere now.
Between classes I attended, I worked at the campus bookstore.
For everything he did, he should be punished severely.

SEPARATING COMMA.53: Use a comma after a prepositional phrase that contains a verbal when the
phrase comes at the beginning of the sentence.
After reaching a verdict, you will return to this courtroom.
For me to solve the problem, I will need more information.
In years to come, he will rue the day he met this woman.

SEPARATING COMMA.54: Use a separating comma after an objective case noun clause that has been
pulled out to the beginning of the sentence.
(Where it was located), I don't know.
Where it was located is the direct object of do know.
(How far he walked), he does not want to tell us.
How far he walked is the object of the infinitive to tell.
(What he is doing), she doesn't relate to.
What he is doing is the object of the preposition to.

SEPARATING COMMA.55: Use a separating comma after an adverb clause that begins a sentence.

If necessary, finish it tomorrow.
When he arrived, he went straight to work.
Because there was a commotion, I didn't stop.

SEPARATING COMMA.56: When any introductory element begins a sentence that could not possibly
start a new conversation, use a comma after the introductory element.
On the other hand, do you remember the date?
In conclusion, I want to point out the circumstances around this incident.
However, he had to get his marriage annulled before he could move forward.

SEPARATING COMMA.57: If an element does not need a comma after it at the beginning of the
sentence, do not use a comma after it just because the sentence begins with a coordinate conjunction.

Every Tuesday we had the same ritual.
And every Tuesday we had the same ritual.
In the afternoons he would frequently need to rest for a while.
But in the afternoons he would frequently need to rest for a while.
Every day I waited eagerly for the mail to come.
And every day I waited eagerly for the mail to come.

SEPARATING COMMA.58: If an element needs a comma after it at the beginning of the sentence, use a
comma when the sentence begins with a coordinate conjunction unless the element is one that always
needs commas around it, in which case use a pair of commas around the element.
Late in the day on Friday, she was In no mood to try to fix his mess.
But late in the day on Friday, she was in no mood to try to fix his mess.
Standing in the yard, I could clearly see that there was no one at home.
And standing in the yard, I could clearly see that there was no one at home.
As he was turning the corner, he seemed to lose control of the car.
But as he was turning the corner, he seemed to lose control of the car.

SEPARATING COMMA.59: Use a comma any time that it will prevent a misreading or it will add clarity
to a sentence.
In general, audits were conducted the end of each month.
I think not, since he has to be here anyway.
Before, he worked for an automotive company.

## THE COMMA THAT SETS OFF

SETTING-OFF COMMA.1: Use a pair of commas around the state when it follows the city.
He lived in Omaha, Nebraska, for several years.
Culver City, California, is the correct mailing address.
she wanted to set up a business in Salem, Oregon, near her sister.

SETTING-OFF COMMA.2: When the ZIP code follows the city or state, do not surround the ZIP code
with its own set of commas, but include the ZIP code as a unit with whatever it follows.
I know that it is Indianapolis, Indiana 46224, where she practices.
Oxnard 93030 is the location.
she works in Fort Myers, Florida 33309, as a computer programmer.

SETTING-OFF COMMA.3: When the city-state unit with or without the ZIP code is a direct adjective --
that is, it is in front of the noun it modifies -- use a pair of commas around the state after the city, OR
omit the comma after the state before the noun that is modified.
The Phoenix, Arizona, climate is what she needs.
The Phoenix, Arizona climate is what she needs.
I saw the Denver, Colorado, statistics for that period.
I saw the Denver, Colorado statistics for that period.
she moved to Burien, Washington 98166, area in the summer of last year.
She moved to Burien, Washington 98166 area in the summer of last year.

SETTING-OFF COMMA.4: Use a pair of commas around the year when it follows the month and the
date.
It was July 20, 1969, that man landed on the moon.
September 11, 2001, will live forever in our memories.
The election on November 4, 2008, was historic.

SETTING-OFF COMMA.5: When the year follows the month alone, use a pair of commas around the
year, OR omit the commas.
It was July, 1969, that man landed on the moon.
It was July 1969 that man landed on the moon.
September, 2001, will live forever in our memories.
September 2001 will live forever in our memories.
The election in November, 2008, was historic.
The election in November 2008 was historic.

SETTING-OFF COMMA.6: Use a pair of commas around titles that follow names -- e.g., Jr., R.N., M.D..,
Esq. -- with the exception of Roman numerals.

Jeffrey Mills, Sr., accompanied us to the bank.
Charlotte Adams, Ed.D., addressed the concerns of us all.
We sent it to Matthew Solomon III for his approval.

SETTING-OFF COMMA.7: Use a pair of commas around contrasting elements. -- e.g., Jr., R.N., M.D.,
Esq.
it was not Jerry, rather Bob, who turned on me.
I saw her at work, seldom anywhere else, during that period of time.
She was always with a crowd, never alone, when this happened.

SETTING-OFF COMMA.8: If there is a coordinate conjunction before the contrasting element, do not
use any punctuation for the contrasting element.
It was CBS and not NBC that first reported the event.
The suspect claimed major injuries and never minor scratches.
She listened intently but seldom knew the answers,

SETTING-OFF COMMA.9: When there are lead-in words before quoted material, put a comma after
the lead-in words and another mark of punctuation to close off the quote before the sentence goes on.

He said, "Leave here at once," and pointed to the door.
She screamed, "Get away from me," as she began to sob.
Did he say, "You owe me money," walking out and slamming the door?
He said, "Are you telling me to leave?" and pointed to the door.
She screamed, "Why are you doing this?" as she began to sob.
Did he say, "Do you want me to call the police?" walking out and slamming the door?

SETTING-OFF COMMA.10: Use a pair of commas around a nonessential noun appositive in the middle
of the sentence.
We met with Ms. Ray, president of the company, later that same day.
The lone suspect, the one in blue over there, was sitting in the car.
The top-selling agent, Marianne Brown, had been with us only three years.

SETTING-OFF COMMA.11: Use a pair of commas around a nonessential adjective when it follows the
word it modifies and comes in the middle of the sentence.

she saw the child, dirty and obviously hungry, peek out.
The bartender, cool and unruffled, listened to him.
My newest client, wealthy beyond words, tried to cheat me.

SETTING-OFF COMMA.12: Use a pair of commas around a nonessential participle when it follows the
word it modifies and comes in the middle of the sentence.
The lone gunman, lying behind the car, lunged forward.
My only son, attending a university in another state, lives on Campus.
Harry Youngman, tired from the hectic schedule, took a month's leave of absence.

SETTING-OFF COMMA.13: Use a pair of commas around a nonessential adjective clause when it
comes in the middle of the sentence.
John Webster, who was driving the car, had not been drinking.
We saw our family doctor, who prescribed that medication.
My father, who was a psychiatrist, refused to treat her.

SETTING-OFF COMMA.14: Use a pair of commas around the tag clause that echoes the question when
it is in the middle of a sentence.
You saw her later that night, didn't you, at the after-hours club?
Mr. Warren had seen it, had he not, before it was released to the public?
They were delivered, were they not, before the end of the working hours?
He was watching, wasn't he, from the car?
You did state, did you not, that he was 16 at the time?
His accusations were not far, were they, from the truth?

SETTING-OFF COMMA.15: Put a pair of commas around direct address.
Yes, ma'am, we did see her there.
Please weigh, ladies and gentlemen, Its importance.
We need to understand, Doctor, the function of this.
I am wondering, Judge, when we are going to take the morning recess.
You had better be here, buddy, when I am ready to leave.
she left, Carol, when you did.

SETTING-OFF COMMA.16: Use a pair of commas around a nominative absolute when it comes in the
middle of the sentence.

He left, his task completed, around 10:00 in the morning.
She stayed, the news not being good, for further tests and blood work.
We called for another vote, the decision as yet unmade, for 3:00 P.M.

SETTING-OFF COMMA.17: Use a pair of commas around a parenthetical in the middle of a sentence.

one was riding alone, however, because of the mix-up.
I had it, by the way, when I saw you last week.
I cannot remember, though, when she was there.

SETTING-OFF COMMA.18: Use a pair of commas around a subject and verb being used
parenthetically in the middle of the sentence.
It was on, I believe, the fourth Saturday of the month.
She was frustrated, it seems to me, with the situation.
she was, I'd say, over six feet.

SETTING-OFF COMMA.19: Use a pair of commas around a mild interjection in the middle of a
sentence.
We were standing, oh, why, 50 feet from the intersection.
He had given me, gee, a lot of money, say, in the past months.
They had come down, well, just to see us.

SETTING-OFF COMMA.20: Use a pair of commas around a "throwaway" word in the middle of the
sentence.
We were, like, you know, worried, you know, about it.
Are you saying, then, that you do not know the brand?
Where did you go, now, when he told you to leave?

SETTING-OFF COMMA.21: Use a pair of commas around a number or letter that denotes a list.

And, C, there is no evidence to support this absurd argument.
I want to mention, in the first place, that this is not according to the rules we set out.
This ts, lastly, not something that he ever would have agreed to.

SETTING-OFF COMMA.22: Use a pair of commas around a neutral remark when it comes in the
middle of the sentence.

Do you know, sitting here today, the exact date that the contract was signed?
He was, to the best of my knowledge, fully licensed to practice in this state.
I cannot remember, off the top of my head, the exact numbers.

SETTING-OFF COMMA.23: Put a pair of commas around intervening elements that come between the
subject and verb.
The suspect, along with his accomplices, had rifles.
His teenaged daughter, like so many others, has had some problems.
The manager, together with her employees, went on a weekend retreat.

SETTING-OFF COMMA.24: Put a pair of commas around an adverb clause that comes in the middle of
the unit it modifies into.
He called, (when the meeting ended), with the figures.
How long, (after the accident happened), did it take?
I left, (because I didn't feel well), to go to the doctor.
He was alone at the time [because, (when he arrived), everyone else was in a meeting].
If, (after you sign in), you give me your email address], I will send this to you.
He was able to call [since, (before he left town), he took all of our information].

SETTING-OFF COMMA.25: Put a pair of commas around prepositional phrases that are out of order in
the sentence and interrupt the flow.
Were you, at the time of the incident in question, driving under the influence?
She, at the end of a day of work, would be totally exhausted.
it was certain, after the meetings of all of the execs, that the company would close.

SETTING-OFF COMMA.26: Put a pair of commas around a prepositional phrase that begins with of
that follows a proper name and indicates a place of origin or a place of business.
Jonathan Michaels, of Lambert and Tripton, was present.
We met Barbara Hale, of Atlanta, at the convention.
I spoke with Mr. Zytowski, of Microsoft, about the issue.

SETTING-OFF COMMA.27: If an element is always surrounded by commas, put commas around it
after a coordinate conjunction at the beginning of a sentence.

And, in my judgment, this is not a punishable offense.
Or, at any rate, I will see it when I review the files.
But, on the other hand, he has not paid the Dill in full.
She had a sore foot; but, as I see it, it should not have prevented her participation.
The boys usually got along; ana, by the way, so did the girls in the class.
The car was out of control; and, well, there was just nothing I could do.

## THE ABBREVIATION

ABBREVIATION.1: Do not use spaces between the letters of an abbreviation except between initials for
someone's first and middle names.
He is an agent for the DEA.
I want to be sure that he has ID.
she has earned an M.A. in literature.
M. J. Johnson is my advisor.
We called Dr. L. D. Udell for an opinion.
One of my favorites is C. S. Lewis.

ABBREVIATION.2: Use a standard dictionary to research the capitalization of the letters of an
abbreviation.
She works at headquarters for NCRA.
It is a Btu measurement.
The car has an excellent mpg rating.

ABBREVIATION.3: When the letters of the abbreviation stand for a proper name, capitalize the
abbreviation.
The FDA is handling it.
Food and Drug Administration
It was an interview with IBM.
International Business Machines
He is a member of the CBS team.
Columbia Broadcasting System

ABBREVIATION.4: Capitalize the letters of an acronym unless you find it otherwise in a standard
dictionary.

It has been a very successful CORE project.
She is using an Eclipse CAT system.
He is in the country for a NATO meeting.

ABBREVIATION.5: Do not use periods in abbreviations that represent governmental agencies.

Her work involves frequent contact with the EPA.
Is the FCC in control of this issue?
The ICC is regulating that practice.

ABBREVIATION.6: Do not use periods in abbreviations that have more letters than words they
represent, that is, where each letter does not stand for a separate word.
My brother watches too much TV.
She was found under the influence of LSD.
He has played QB the whole season.

ABBREVIATION.7: Do not use periods in abbreviations that represent call letters for a radio or TV
station.
KFWB is an all-news station.
He works for WISH on the East Coast.
He won $10,000 from radio station KRLA.

ABBREVIATION.8: Do not use periods in the abbreviation IOU and SOS.
He signed an IOU for the merchandise.
The SOS was sent out two hours ago.
I knew he would not honor the IOU.

ABBREVIATION.9: Do not use periods for letters that stand for hypothetical people or entities.

Let's suppose Mr. A lends Mr. B the sum of $500.
If Student A improves by 10 percent, he will Surpass Student B.
Let's say you go to XYZ Lending.

ABBREVIATION.10: With a few exceptions, do not use periods in the common abbreviations.

She attended UCLA to do graduate work.
He has a CSR license from California and his RPR.
We needed the ISBN for her book.

ABBREVIATION.11: Use periods (and spaces) with initials for a person's name.
I spoke with M. P. Jackson about the job.
R. A. Perez was nominated to the post.
He is a first cousin to Y. E. Matthews.

ABBREVIATION.12: Use periods with the abbreviation U.S. for "United States," if said as an
abbreviation, and with the abbreviations for cities, if said.
It is U.S. policy in the region, I believe.
I decided to come to L.A. in the summer of 1984 for the Olympics.
N.Y.C. is a happening place.

ABBREVIATION.13: Use periods with A.M. and P.M.
He arrived home at 2:00 A.M.
The 4:00 P.M. appointment was with her psychiatrist.
is that A.M. or P.M.?

ABBREVIATION.14: Use periods with B.C./A.D. and B.C.E./A.C.E.
It is reported to have occurred in 56 B.C.
It was recorded in 450 A.D.
She read that it was dated 120 B.C.E.

ABBREVIATION.15: When there is an abbreviation that has a period after it at the end of the sentence,
do not use a second period to end the sentence; however, use the question mark and any other
punctuation as usual.
The meeting began a little after 3:00 P.M.
He is Frank Johnson, Jr.
He has lived his entire life in the U.S.
she is an M.D.: is that correct?
Did you arrive at 5:00 P.M.?
These are the times for Joseph Wright, Sr.: 3:00, 5:00, 6:00.

ABBREVIATION.16: Use periods and lowercase letters for i.e. (meaning "that is") and e.g. (meaning
"for example"), which are always surrounded by some kind of punctuation.
He was convicted of a most heinous crime, i.e., murder.
She had many problems; e.g., she was a diabetic.
The doctors I had seen -- e.g., Dr. Bedrozian -- had not diagnosed the problem.

ABBREVIATION.17: Use uppercase letters, no periods, and no spaces when a word is reduced to letters.
If the abbreviation is used as a verb, use apostrophe d for the past tense, apostrophe s for the present
tense, and apostrophe ing for the participle form.
When he OD'd, he was carrying over $10,000.
He ID's all of his patients before surgery.
We are ID'ing him tomorrow morning.

ABBREVIATION.18: Use uppercase letters and no periods for the designation of an airport whether it is
said as a word or as individual letters.
He is coming in at LAX around 6:00.
The SFO tag on my luggage came off.
We had to land at BWI and take the train.

ABBREVIATION.19: Abbreviate and use a period for Mr. and Mrs. as titles in front of the name.

The police report included Mr. Chapple.
Mrs. Lipton filled in for me that day.
It was sent to Mr. and Mrs. Parker for their signature.

ABBREVIATION.20: Use a period after Ms. as a title in front of the name even though it is not an
abbreviation. Do not use a period with Miss in front of the name as it is not an abbreviation.
He called in Ms. Theresa Howard to consult.
Miss Henderson was part of the team.
Ms. Friedman was head of the company.

ABBREVIATION.21: Abbreviate and use a period with the word doctor when it is used as a title in front
of the name; write it out and capitalize it in direct address; write it out with a lowercase letter 1n context.

I sent the test results to Dr. DeWitt.
Please tell me, Doctor, what your opinion is.
I went to the doctor three days a week.

ABBREVIATION.22: Write out and capitalize the titles Honorable and Reverend in front of the name.

It is The Honorable Peter Lyons presiding.
We were married by The Reverend Jordan Peters.
The Reverend Maris Almeida is now the rector in charge of the parish.

ABBREVIATION.23: Write out and capitalize titles in front of names and in direct address; write them
out but do not capitalize them in context.
It was reported that Sergeant Gerson conducted the examination.
I want to know, Sergeant, what your impression is of his capacity.
He said that the sergeant did not respond promptly.
It was Senator Romano that led the fight.
Please tell me, Senator, your opinion on this bill.
I spoke with the senator on Friday.
Have you conferred with Counsel Roddick today?
Would you tell me, Counsel, what you mean by that.
He invited counsel to join him in chambers.
It was Officer Guerrero that was at the scene.
As you testify, Officer, please keep your voice up.
I spoke to the officer the following day.

ABBREVIATION.24: In general, abbreviate the word saint and use a period after it as a title in front of a
name. The feminine form of the abbreviation is Ste.
We attended St. James on a regular basis.
The defendant was born in St. Louis.
Later we moved to Sault Ste. Marie.

ABBREVIATION.25: Write out the words mount, port, point, and fort as part of a proper name.

He lived in Port Angeles for three years.
I was sent to Fort Lauderdale, Florida, to the corporate offices.
It is on the base at Point Mugu.

ABBREVIATION.26: Abbreviate the words junior and senior, and use a period after them and commas
around them as titles after the name.
I spoke with John Scott, Jr., about taking the position.
Mark L. Branson, Sr., was in charge.
He put A. W. Wells, Jr., in charge.

ABBREVIATION.27: Abbreviate the word esquire and use a period after it and commas around it when
it is used after the name as a title.
We consulted Walter Riskin, Esq., at the trial.
she was represented by Carol Jacobs, Esq.
Roberta Gomez, Esq., joined the defense.

ABBREVIATION.28: Use periods for degrees and professional titles.
He referred me to Jacob Winchell, M.D., for the problem with my knee.
JoAnna Martine, P.A., was the lead on my case.
I believe she talked to Thomas Harding, R.N.

ABBREVIATION.29: When a possessive is added to the abbreviation or title after a name, add
apostrophe s to the abbreviation or title, and omit the comma after it.
Byron George, Jr.'s dad was here.
Robert Pennington, M.D.'s dad is here.
It was Robert Taylor, Esq.'s case to defend.

ABBREVIATION.30: Do not use periods within or commas around Roman numerals as a title after the
name. Do not transcribe the word the that comes between the name and the number.
I nominate Charles E. Barnes III for president.
Joseph Allen IV was given the honor.
Henry VIII had several wives.

ABBREVIATION.31: In general, do not reduce a spoken word to an abbreviation or a symbol with the
exception of the titles previously mentioned.

Incorrect: It was 30 ft. across.
Correct: It was 30 feet across.
Incorrect: He lived on Macon Blvd.
Correct: He lived on Macon Boulevard.
Incorrect: It weighed over 2,000 lbs.
Correct: it weighed over 2,000 pounds.
Incorrect: #17 has been lost.
Correct: Number 17 has been lost.
Incorrect: It was raised by more than 5%.
Correct: It was raised by more than 5 percent.

ABBREVIATION.32: If a shortened form of a word is said and is a recognizable form, transcribe it as
said without a period.
He works as a rep for the bank.
She needs to be closer to the mike.
He posted an ad to offer his condo for sale.

ABBREVIATION.33: Use the full name of the state, not the two-letter abbreviation.
She grew up in Bloomington, Indiana.
Salem, Oregon, is a desirable place to live.
I think there is an office at 111 State Street, Rochester, New York.

ABBREVIATION.34: Abbreviate the word number as No. -- Nos. in the plural -- in front of a figure
except at the beginning of a sentence, where the word number is written out.
I want to look now at No. 5.
I would like these admitted as Nos. 10 and 11.
Number 20 is the next in order, I believe.

ABBREVIATION.35: Abbreviate the word versus as v. or vs. in a case being litigated or cited, and write
out the word versus in the body of a transcript.
We are here for purposes of a preliminary hearing in People vs. Bell.
It was a heated discussion of Roe v. Wade.
It was a friendly exchange about USC versus UCLA.

ABBREVIATION.36: Use the form X ray as a noun and x-ray as a verb and adjective.
I shall need an X ray of the femur.
she had x-rayed the bone from every angle.
The x-ray plate gives no definitive answer.

ABBREVIATION.37: Write out the word okay as a full word.
It is okay with me.
The boss okayed the proposal without a question.
Okay. I now want to discuss your termination.

ABBREVIATION.38: Do not use a period after the Latin word et. It is not an abbreviation.

Matthew, Mark, Luke, et seq., will be studied.
James Harris, et al., joined the lawsuit.
He tried to sell books, vacuum cleaners, Tupperware, et cetera.

## THE APOSTROPHE

APOSTROPHE.1: To create the singular possessive, add apostrophe s to the singular form of the word
without any exceptions in the language.
SINGULAR SING. POSS. SINGULAR SING. POSS.
man man's child child's
boy boys student Students
lady lady's dancer dancer's
class class s witness witness's
boss boss s bass bass's
actress actress's fox fox's

APOSTROPHE.2: To create the possessive for plural words that end in s -- most of them do -- just add
an apostrophe to the plural form of the word.
SINGULAR PLURAL PLURAL POSSESSIVE
girl girls girls'
attorney attorneys attorneys
teacher teachers teachers'

church churches churches'
witness witnesses witnesses:
fox foxes foxes'

APOSTROPHE.3: To create the possessive for plural words that do not end in the letter s, add an
apostrophe s to the plural form of the word.
SINGULAR PLURAL PLURAL POSSESSIVE
man men men's
child children children's
ox oxen oxen's
aide-de-camp aides-de-camp aides-de-camp's
sister-in-law Sisters-in-law Sisters-in-law's
Senator-elect senators-elect senators-elect's

APOSTROPHE.4: Add apostrophe s to the singular form of a name to make it possessive even when the
name ends in an S.
SINGULAR SING. POSS. SINGULAR SING. POSS.
Mr. Samson Mr. Samson's Ms. Nelson Ms. Nelson's
Ms. Kennedy Ms. Kennedy's Mr. Rood Mr. Rood's
Mr. Yoshida Mr. Yoshida's Ms. Nang Ms. Nang's
Mr. Hess Mr. Hess's Ms. Ross Ms. Ross's
Ms. Ruiz Ms. Ruiz's Mr. Sanchez Mr. Sanchez's
Mr. Wells Mr. Wells's Ms. Andrews Ms. Andrews's

APOSTROPHE.5: If the plural of the name ends in s -- most of them do -- add the apostrophe alone to
form the plural possessive.
SINGULAR PLURAL PLURAL POSSESSIVE
Mr. Allen the Allens the Allens'
Ms. Stone the Stones the Stones'
Ms. Wilson the Wilsons the Wilsons'
Ms. Wells the Wellses the Wellses'
Mr. Pickens the Pickenses the Pickenses'
Ms. Hopkins the Hopkinses the Hopkinses'

APOSTROPHE.6: If the name ends in s, z, x, the soft ch, or sh, add -es to make it plural without regard
to how it might be pronounced; then add the apostrophe for possessive where the content calls for it.

SINGULAR PLURAL PLURAL POSSESSIVE
Mr. Marsh the Marshes the Marshes house
Ms. Fox the Foxes the Foxes' house
Mr. Hernandez the Hernandezes the Hernandezes' house
Mr. Lewis the Lewises the Lewises' house
Ms. Hicks the Hickses the Hickses' house
Ms. Fuentes the Fuenteses the Fuenteses' house

APOSTROPHE.7: When a surname has the word the in front of it, make the name plural without regard
to how it might be pronounced.
Mr. and Mrs. Crosby the Crosbys
Rick and Mark Hiramoto the Hiramotos
Jen and Howard Chan the Chans
Rob and Bill Martinez the Martinezes
Margaret and William Flores the Floreses
Mr. and Mrs. Jones the Joneses

APOSTROPHE.8: Do not change the base spelling of a proper name when making it plural or when
making it possessive.
I spoke with Ms. Kennedy's secretary.
The Kennedys attended the inaugural dinner.
I spoke with the Kennedys' son that evening.
There are two Jennys in the organization.
Both Harrys were from the same family.
The Wakemans' home is in Long Beach.

APOSTROPHE.9: Decide whether you need singular possessive, just plain plural, or plural possessive.
Then choose the correct form.
I know that Mr. Hess's share was more than mine.
We spent time with the Hesses on several occasions.
The Hesses' son was also involved in the operation.

I spoke with Mr. Rogers's representative on more than one occasion.
I believe the Rogerses were a part of the operation from the beginning.
The Rogerses' share increased over time.

APOSTROPHE.10: Do not use an apostrophe when all you need is the plural form of a proper name.

Incorrect: We spent the evening with the Oliver's.
Correct: We spent the evening with the Olivers.
Incorrect: The Gaines' were involved in the scheme.
Correct: The Gaineses were involved in the scheme.
Incorrect: I sent the copies to the Thompson's.
Correct: I sent the copies to the Thompsons.

APOSTROPHE.11: Be sure to choose the correct singular/plural form of the possessive: singular for one,
plural for more than one.
...the story of the witness... ...the witness's story...
...the stories of the witnesses... ..the witnesses stories...
...the car of Ms. Callas... ...Ms. Callas's car...
...the car of the Callases... .. the Callases' car...
...the job of the boss... ...the boss's job...
...the jobs of the bosses... ..the bosses jobs...
The plaintiffs mother verified his story.
The plaintiffs' mothers verified their stories.
I notice the defendant's wife is in court today.
I notice the defendants' wives are in court today.
I spoke with Ms. Harris's attorney.
He spoke with the Harrises' attorney.

APOSTROPHE.12: When ownership is being expressed, use an apostrophe for the possessive form even
when the noun being modified is not present.
Our prices are lower than our competitors' prices.
Our prices are lower than our competitors .

she constantly compared her job to her sister's job.
she constantly compared her job to her sister's.
Mr. Ross's files are here at the doctor's office.
Mr. Ross's are here at the doctor's.

APOSTROPHE.13: Do not use an apostrophe for possessive pronouns.
Incorrect: I saw her's in front of the house that night.
Correct: I saw hers in front of the house that night.
Incorrect: Ours' is not on the list to be removed.
Correct: Ours is not on the list to be removed.
Incorrect: I have their's in the car.
Correct: I have theirs in the car.

APOSTROPHE.14: Select a consistent style, and use an apostrophe or not to make numbers plural.

The number is in the 7Os.
The number ts in the 70s.
He was born in the 1980s.
He was born in the 1980's.
She is in her 90s.
She is in her 90's.

APOSTROPHE.15: Use an apostrophe to make letters plural.
she put X 's in several places on the diagram.
He has mastered the ABC's of the position.
There were three P.S.'s to the letter.

APOSTROPHE.16: Use an apostrophe to indicate that part of a word or number is missing.
We've heard that he couldn't finish the project.
It was in late '69 that man landed on the moon.
Didn't it occur in '45 right at the end of the war?

APOSTROPHE.17: Use an apostrophe for a direct adjective construction in which time, value, distance,
or amount is indicated about the noun. Use an apostrophe s when the time indicated is singular in
concept and s apostrophe when the time indicated is plural.
There was an hour's break between sessions.
They stole hundreds of dollars' worth.
The lake is three miles' walk from here.
We took one week's vacation.
We took two weeks' vacation.
She had a dollar's worth of candy.
she had several dollars' worth of candy.
it is a mile's drive from here.
It is five miles' drive from here.

APOSTROPHE.18: Use the apostrophe in idiomatic expressions based on the same concept in
Apostrophe.17.
...for Pete's sake...
...a stone's throw...
for heaven's sake...

APOSTROPHE.19: Use a hyphen for the direct adjective combination when it forms a unit and is said
without the s.
We took one week's vacation.
We took a one-week vacation.
We took two weeks' vacation.
We took a two-week vacation.
She took three hours' break to go home.
She took a three-hour break to go home.

APOSTROPHE.20: Use an apostrophe, either apostrophe s for singular or s apostrophe for plural, for
the noun in front of the gerund.
She did not tolerate John's drinking.
There is no reason for his parents' constant arguing.
There was a real gap in Carol's thinking.

## THE HYPHEN

HYPHEN.1: Add common prefixes directly to the front of a word to form a solid word.
postmortem nonentity ultraviolet
prenuptial Superpowers subnormal
redo subtext hypoglycemia

HYPHEN.2: Hyphenate the prefix to the word when the word being created already exists in the
language with a different meaning.
He wanted to multiply the holdings of the company by three.
This project calls for multi-ply boards.
The chicken coops in her backyard were a problem for the neighbors.
He belongs to a farming co-op In the city.
He works in a unionized shop.
It is an un-ionized compound.

HYPHEN.3: Hyphenate the prefix to the word when the word is a proper noun, that is, when it is a
capitalized word.
lam anticipating a mid-June release.
It is a pro-Republican point of view.
His behavior was thought of as un-American.

HYPHEN.4: Hyphenate certain vowel combinations that do not normally exist in the language or that
form combinations that are difficult to read.
He complained of intra-abdominal pain.
It is an anti-inflammatory drug.
It was an intra-accounting department problem.

HYPHEN.5: Hyphenate certain prefixes when ease of reading is the issue.
He is a co-director of the company.
His co-workers did not have good things to say about him.
The ex-editor of the magazine was brought in.

HYPHEN.6: Always hyphenate the prefix self-. If it is the root word, make it a solid word.

Her self-confidence is waning after the ordeal.
It is a self-serving conclusion.
The doctor stressed the importance of self-examination.
He had the selfsame idea.
It was clear she was a very selfish person.
His selfless efforts made the difference.

HYPHEN.7: When a compound noun is more than one word, whether it is hyphenated or separate
words, hyphenate the prefix to the front of the first word.
That was in her pre-real estate days.
it happened to him in his post-free agent stage.
She had multi-in-law problems.

HYPHEN.8: Add normal suffixes directly to the end of the word to form a solid word.
citywide daylong fireproof
countywide weeklong childproof

HYPHEN.9: Add the suffix -like to form a solid word for regular words unless the word ends in two ls,
where the suffix is hyphenated.
It is a lifelike replica of him.
It is a churchlike structure.
He seemed childlike in his speech.
It had a bell-like shape.
The ball-like object landed at my feet.
There was a shell-like design in the wallpaper.

HYPHEN.10: Add the suffix -wise to make a solid word for regular words. In some of the more
"unusual" combinations, hyphenate the suffix wise.
It was shoved into the space lengthwise.
I could not get a word in edgewise.
He turned it in a clockwise direction.
What do I do with this sentence punctuation-wise?
Statistics-wise, this is a wash.
He is very conscientious environmental-wise.

HYPHEN.11: When a compound noun is multiple words, whether hyphenated or separate words,
hyphenate the suffix to the end of the last word.
It was an assembly line-like job.
Social security-wise, the figures were of no value to me.
Runs-batted-in-wise, he is below his usual production.

HYPHEN.12: Follow the form of a compound noun as it is listed in the standard dictionary: one word,
multiple words, or hyphenated.
pipe organ round-robin roughneck
pink slip ill-usage painkiller
image tube keep-away iceberg

HYPHEN.13: Keep the "little" word that forms an idiomatic expression separate for the verb and verbal
form. Check a standard dictionary to see whether the noun form is one word or hyphenated.
NOUN VERB
built-in built in
get-together get together
breakthrough break through
There was an attempt to take over the company. verbal
The takeover was not successful. noun
He was ordered to stake out the area over the course of a week. verbal
The stakeout did not net any new results. noun
Did you drive through rather than go inside? verb/adverb
The drive-through was closed for repairs. noun

HYPHEN.14: Do not change the form of a compound noun when it is used as a direct adjective.

...IN real estate... by a faith healer... ...on life support...
...real estate agent... ...faith healer ministry... ...life Support system...
The incident occurred near the high school. noun
She was a high school senior at the time. Adjective

He joined the Marine Corps after graduation. noun
She is a Marine Corps sergeant. adjective
She is my sister-in-law. noun
There were sister-in-law issues, I believe. adjective

HYPHEN.15: Hyphenate two nouns which have different meanings but are used to refer to the same
thing or the same person.
He is an actor-director on the movie.
Mr. Willis has been elected secretary-treasurer.
Ms. Garson is the manager-consultant there.

HYPHEN.16: Hyphenate a compound noun that repeats, rhymes, or simply changes a vowel.

That is a definite no-no.
The kids were playing with a walkie-talkie.
He did a flip-flop in his attitude toward her.

HYPHEN.17: Generally hyphenate a compound noun that is made up of a letter-word combination.

He lives in an A-frame.
It is illegal to make a U-turn there.
It occurred at a T-intersection.

HYPHEN.18: Use an upper case letter for the noun form X ray. Use a lower case letter and a hyphen for
the adjective and verb forms.
I need to see the X ray to make that determination. noun
The knee was x-rayed on two occasions. verb
The x-ray film was unclear. adjective

HYPHEN.19: Use a hyphen between two nouns that have an understood to, through, or and between
them.
The New York-Washington flight was delayed.
There will be an air-sea search.
He was practicing takeoff-landing maneuvers.

HYPHEN.20: Use a hyphen when the compound noun does not have a noun form in it.
She continues to live in make-believe.
I always wore hand-me-downs.
There is no give-and-take here.

HYPHEN.21: Use a hyphen in plane models between the letter and the number.
It is an L-1011.
She flew the DC-10.
The F-16 is a military plane.

HYPHEN.22: Do not hyphenate civil and military titles.
The second lieutenant was put In charge.
The chief of police has given the report.
The Vice President will arrive later today.

HYPHEN.23: Use the appropriate form, hyphenated or not, to secure the meaning of a compound
noun.
He is a small businessman.
short in stature
He is a small-business man.
owns a small company
He is an assembly lineman.
lineman works on telephone lines
He is an assembly line man.
works on an assembly line, which is a compound noun

HYPHEN.24: Look up compound verbs in a standard dictionary to find the correct form.
We need to double-check those figures.
It was not a good idea to try to jerry-rig the construction site.
The value of the stock has been downgraded.

HYPHEN.25: To show that two or more words form one unit in front of a noun, use a hyphen to tie
them together.

She was an in-your-face kind of person.
It was a two-lane highway in each direction.
His thoughts were that it was just an old-fashioned idea.

HYPHEN.26: To show that a number and a word form one unit in front of a noun, use a hyphen to tie
them together.
The 55-year-old man entered the hospital.
He took the $56,000-a-year job.
He used five 20-foot boards to complete it.

HYPHEN.27: If two or more words do not form a unit but modify the noun separately, do not use a
hyphen between them.
It was a large black cabinet.
Large and black modify cabinet separately.
she was a small older woman.
Small and older modify woman separately.
They had their last meeting in November.
Their and last modify meeting separately.

HYPHEN.28: If two or more words already represent a unit, do not hyphenate them.
income tax social security high school
income tax payment social security check high school graduation
senior citizen real estate credit card
senior citizen event real estate transaction credit card debt
due diligence genital herpes general admission
due diligence process genital herpes outbreak general admission ticket

HYPHEN.29: When the adjective that is a unit comes after the noun it modifies, do not use a hyphen.

I have long-range plans to go to graduate school.
My plans for graduate school are long range.
It is a one-way street.
The street is one way.

His far-reaching goals are admirable.
It is admirable that his goals are far reaching.

HYPHEN.30: Do not hyphenate proper adjectives, i.e., those that are capitalized.
The Santa Barbara residents were adamant.
The Supreme Court decision was unpopular.
The White House staff was helpful.

HYPHEN.31: Use a hyphen when two separate and distinct proper names are used together to form a
one-unit adjective.
The Greek-American resident was treated well.
The Lincoln-Venice intersection is a busy one.
It occurred near the Israel-Jordan border.

HYPHEN.32: Do not hyphenate an adverb ending in -ly to the adjective that follows it when they
precede a noun.
The newly discovered paintings date back to 1700.
Those are recently built condominiums.
He is a uniquely qualified candidate.

HYPHEN.33: When the modifying words form a unit and come from actual words that could be said,
either hyphenate the combination or quote it.
His "I don't give a darn" attitude angers me.
His I-don't-give-a-darn attitude angers me.
He gave me that "Leave me alone" look.
He gave me that leave-me-alone look.

HYPHEN.34: Do not hyphenate percentages when they are direct adjectives as the number and word
are already considered to be a unit.
There was a 44 percent increase in costs.
A 50 percent cut in staff was announced.
He took a 10 percent cut In pay.

HYPHEN.35: When an amount over 1,000,000 is expressed as a figure with the word million (and
those above), do not hyphenate the combination when it is a direct adjective because it is already
considered to be a unit.
He received a $5 million grant.
The company has a $16 million debt.
She received a $4 million inheritance from her grandmother.

HYPHEN.36: Do not hyphenate comparison words.
He always picks the higher priced items.
She is the smaller boned woman.
It is a more limited statement than those he usually makes.

HYPHEN.37: Do not hyphenate fractions when they are used as nouns.
Two thirds of the men in the lineup are repeat offenders.
I think it was estimated at three fourths.
The estimate is one fifth of those involved.

HYPHEN.38: Hyphenate fractions used as direct adjectives, those that are right in front of the noun
they modify.
It passed by a two-thirds vote.
We need a three-fourths majority.
This is a one-third increase.

HYPHEN.39: When there are multiple compound adjectives that all share the same last element, an
element that is expressed only once at the end, use a hyphen for each element even when that means that
the hyphen is suspended on the end of the word.
There are first-, second-, and third-floor units.
It includes foreign- and domestic-built cars.
There were 500-, 600-, and 700-pound loads.

HYPHEN.40: Hyphenate letter-for-letter spelling.
I spoke with Mary Donnell, D-o-n-n-e-I-l.
It is 438 Sepulveda, S-e-p-u-l-v-e-d-a, Boulevard.
It is sumatriptan, s-u-m-a-t-r-i-p-t-a-n, that she used.

HYPHEN.41: When spelling letter for letter, follow the way the word looks normally in terms of
capitalization and spacing.
My name is Richard McCall, M-c-C-a-l-l.
W.J. De La Vega, D-e L-a V-e-g-a, was the leader of the project.
I submitted it to van de Mere, v-a-n d-e M-e-r-e.

HYPHEN.42: When only a portion of the word is spelled, put the hyphen in front of the first letter.

Is that -f-f-e or -f-f-y?
It was George Marant, and that is -a-n-t.
That word ends in -o-T.

HYPHEN.43: When the spelling is interrupted, leave the last letter with no hyphen after it, and put a
hyphen in front of the first letter when the spelling picks up again.
It is Carrigan, C, as in "cat," -a-r-r-i-g-a-n.
It is spelled R, as in "Roger," -a-t, as in "Tom," -l-i-n. It is Ratlin.
It is after the character Abelard, A-b, as in "bravo," -e-l-a-r-d, as in "dog."

HYPHEN.44: Use hyphens to separate the elements of a phone number including the area code.

I can be reached at 555-2986.
My number is 213-555-8932.
Please call 1-800-555-9384.

HYPHEN.45: Hyphenate social security numbers, grouped with three, then two, then four digits.

My number is 999-99-9999.
I am reading it as OO0-00-0000.
It is 111-11-1111.

HYPHEN.46: When the numbers 21 to 99 are written in words, use a hyphen.
Twenty-two issues were submitted.
Forty-nine of them were delivered at one time.
Thirty-one houses were destroyed in the fire.

HYPHEN.47: When a street name is a number, do not use a hyphen between the address and the name
of a street.
It is 1484 Eighth Street.
I believe it occurred at 749 Ninth Avenue.
one was living with her sister at 1785 68th Street.

HYPHEN.48: When there is more than one part to an exhibit, use a hyphen to attach the subset to the
number of the exhibit.
1am referring to Plaintiffs Exhibit 1-D.
I want to show you People's Exhibit 4-C.
Defendant's A-1 is a letter dated June 10.

HYPHEN.49: When the subset marker is used alone, keep the hyphen in front of it.
I want to see Exhibit 1-B through -F.
He is referring to D-5 and -6.
It is 17-A, -B, -C, and -D.
Q Are you familiar with 8-F?
A Do you mean -F or -G?
Q I'm sorry. I do mean -G.

HYPHEN.50: When dates are said in figures, use hyphens or slash marks between the units in the date.

I was born 4-17-89.
I was born 4/1 7/89.
It occurred late in the day on 5-29.
It occurred late in the day on 9/29.
We always commemorate the tragedy of 9-11-01.
We always commemorate the tragedy of 9/11/01.

## CAPITALIZATION

CAPITALIZATION.1: Capitalize the first word of a sentence and the first word of any fragment that
stands for a complete thought.

How many were there?
At least 15. I didn't see them all.
Right next to the platform.
Anything else that you remember?
Q A
Q Okay. Fine. Where were you standing?
A
Q A Yes, sir. She was wearing bright red.

CAPITALIZATION.2: Capitalize the first word after a colon only if it is a grammatically complete
sentence.
She referred to several items: a caftan, a scarf, and a burka.
She referred to several items: The first is a caftan; the second is....
I resigned for two reasons: one, underpayment and, two, overwork.
I resigned for two reasons: One is that I was underpaid; two is....
He listed his issues: lack of communication, lack of support, lack of aid.
He listed his issues: He felt there was no communication; he did not feel....

CAPITALIZATION.3: Capitalize the first word inside a quote if the quote is a complete sentence or
stands for a complete thought.
She said, "Not today. I am really busy right now."
I asked, "How do you expect to pull this off?"
He replied, "Not on your life. I will not."
When you use "release," are you referring to some sort of lock?
I believe the witness said "pressure," not "pleasure."
Please describe what you mean "incidental."

CAPITALIZATION.4: Capitalize the adjective form that comes from any proper noun.
He was born in the state of Florida.
It is a Floridian style of construction.
It is an Episcopal church.
He is an Episcopalian.
She is an avid fan of the works of George Orwell.
It is written in the Orwellian style.

CAPITALIZATION.5: Capitalize the names of classes only when the word is always capped or when they
have a course number with them.
I took history, art, and Spanish.
I believe it was an economics class that I was -- Economics 101.
She failed math -- i.e., Calculus 1A -- and had to repeat it.

CAPITALIZATION.6: Capitalize the names of academic degrees, written out or abbreviated, when they
follow a name.
It is an article written by Francisco Franco, Ph.D.
Jonathan Henson, Doctor of Medicine, made the diagnosis.
His colleague on the project, James Edwards, M.A., made the final decision.
He earned a Masters In economics.
I have a Bachelor of Arts in music.
It is a Master's in English.

CAPITALIZATION.7: In general contexts, do not capitalize the name of the degree.
she was not able to complete the doctorate in music.
The master's program is a grueling one.
It is work that will lead to a bachelor's.

CAPITALIZATION.8: Capitalize brand names but not the name of the product that follows it.

He uses Colgate toothpaste.
It is an Amana refrigerator.
I drive a Toyota Camry sedan.

CAPITALIZATION.9: Capitalize the months of the year and the days of the week.
We met on Tuesdays and Thursdays.
Was he born on January 2?
It was Friday, June 5.

CAPITALIZATION.10: Capitalize the names of holidays.

They spent New Year's Eve in Washington, D.C.
We were married on the Fourth of July.
He sent her roses on Valentine's Day.

CAPITALIZATION.11: Capitalize the names of special days.
I will work the polls on Election Day.
We were not given Veterans Day off this year.
He spent Presidents' Day with the family.

CAPITALIZATION.12: Do not capitalize the names of the seasons.
It was early on a Monday morning in the spring of the year.
My hip gives me more trouble in the winter when it is cold.
if I remember correctly, it was sometime in the fall of that year.

CAPITALIZATION.13: Capitalize the words Supreme Court, the word Court, and the words High Court
when they refer to the Supreme Court of the United States.
This matter will eventually go to the Supreme Court.
It was decided by the High Court.
The landmark decision by the Court changed the course of history.

CAPITALIZATION.14: Capitalize the word Justice when it refers to a judge on the Supreme Court and
the words Chief Justice.
She was the first woman Justice.
The Chief Justice sided with the minority on the court.
That Justice cast the lone dissenting vote.

CAPITALIZATION.15: Capitalize the name of a specific court.
This matter will be tried in District Court.
I am working Muni this week.
It was transferred to Superior Court, Department 53.

CAPITALIZATION.16: Do not capitalize the court names when they are used in a generic sense.

It falls under the jurisdiction of a district court.
Only a superior court has that authority.
That can only be decided in a local municipal court.

CAPITALIZATION.17: Capitalize the words Court of Appeal(s) but not the generic appeals court or
appellate court.
The Court of Appeal heard the case.
It was referred to the appellate court.
I know It went up to the appeals court.

CAPITALIZATION.18: Capitalize the word court when it stands alone and refers to a court judge and no
one else. In all other instances, do not capitalize the word court.
The Court will rule on the matter.
It was submitted to the Court for her ruling.
The Court has dismissed the case.
The court will be in session late this evening.
The matter is scheduled to be heard in court later this month.
I just said to him, "I will see you in court."

CAPITALIZATION.19: Always capitalize the word Honor when it refers to the judge Capitalize the word
judge in front of the name as a title and in direct address but not in general context.
I believe Judge Miller presided in that proceeding, Your Honor.
I think Her Honor will likely dismiss it.
We spoke with her last night, Judge, to find out.

CAPITALIZATION.20: Capitalize words like bailiff and clerk in front of the name as a title and in direct
address but not in general context.
I believe that Bailiff Sanchez was in the courtroom that day.
Please hand that to the clerk.
Extra bailiffs were present in the court for the sentencing.

CAPITALIZATION.21: Capitalize the word counsel in front of the name as a title and in direct address
but not in general context.
Will counsel please approach the bench.
I want to know, Counsel, exactly how much longer you will go.
She spoke to Counsel Bagdasanian later in the day.

CAPITALIZATION.22: Capitalize district attorney when it refers to the political entity that the office
represents, and do not capitalize it when it refers to a local office or one of the many district attorneys
that try cases. Capitalize District Attorney's Office only when it represents the entity.
This will be taken up by the District Attorney's Office of Los Angeles.
I spoke with the district attorney on the case.
We will meet in the district attorney's office at 10:00.

CAPITALIZATION.23: Capitalize sheriff when it refers to the political entity that the office represents
and not when it refers to a local office or one of the many sheriffs. Capitalize Sheriff's Office only when it
represents the entity.
The San Dimas Sheriff's Office is investigating the case.
I went into the local sheriff's office.
several sheriffs arrived in response to the emergency call.

CAPITALIZATION.24: Do not capitalize the names of examinations.
I will take him on cross this afternoon.
The direct examination is expected to go several days.
She wants to voir dire him later in the day.

CAPITALIZATION.25: Capitalize the four directions and any of their derivatives when they represent a
generally recognized area.
- On the global scale
There were problems in the Middle East.
It is a South American treasure.
It is different in the Northern Hemisphere.
They made the trek to the North Pole.
It is part of Eastern philosophy.
The West is in alliance on this issue.
He is currently living in Southeast Asia.
We traveled in the South of France.
I believe he is Northern European.

- Within the United States
He is a Northeasterner.
She has traveled extensively in the Southwest.
It is part of the tradition of Southern hospitality.
She lived on the plains of the Midwest
He enjoys the West Coast.
It was the North against the South.
I love the South Side of Chicago.
He lives in Northern California.
The school ts in Northwest Indiana.
= In Southern California, for example
I live in West Los Angeles.
It occurred in the South Bay.
She is a resident of the West Valley.

CAPITALIZATION.26: Do not capitalize the four directions and any of their derivatives when they
represent simply a direction.
Take the 405 north to the 101.
He turned west on Braddock.
She lives just south of Monterey.
You go due north from my house.
We drove east into the sun for what seemed like hours.
It is 20 miles west of Salt Lake.
It occurred in the eastern edge of the county.
She lives in eastern California.
The house is situated on the west side of the airport.

CAPITALIZATION.27: Capitalize any family designation when it is being used in lieu of the name.

Bob saw Mom on Friday.
I think Grandma is going to lend me the money.
she spoke with Father about the investment.

CAPITALIZATION.28: Do not capitalize any family designation when it is being used as simply a
description of the relationship.
My brother saw our mom on Friday.
I think my grandma is going to lend me the money.
My sister spoke with our father about the investment.

CAPITALIZATION.29: Capitalize any family designation when it is being used as a title in front of the
name without any modifier in front of it.
We saw Aunt Margaret on Friday.
He went with Uncle Scott.
I think Grandma Kathy is my favorite.

CAPITALIZATION.30: Capitalize a "family" designation when it is being used in the religious sense.

I will speak with Father about it.
She went to Sister Marie to get help.
I believe the Brothers will attend the convention.

CAPITALIZATION.31: Capitalize the titles of heads of state.
The President-elect has decided to give a policy speech.
I spoke with the Prime Minister late in the day.
She is seeking an audience with the Queen.

CAPITALIZATION.32: When these words refer to other than the head of state, capitalize them
according to the capitalization rules for regular titles.
I know that Washington was the President at the time.
referring to George
I know that Washington was the president at the time.
referring to those other than George
We needed to bring this to the attention of the President.
when it is President of the United States
We needed to bring this to the attention of the president.
when it is not the President of the United States

She thinks she wants to marry the King.
when it is the King of a country
She thinks she should live like a queen.
when it is not the queen of a country

CAPITALIZATION.33: When vice president refers to the Vice President of the United States, capitalize
both words, and do not use a hyphen.
The Vice President went on a tour of the devastated area.
He did not accept the nomination for Vice President.
Vice President Gore went on to win a Nobel Prize.

CAPITALIZATION.34: When vice president refers to other than the head of state, capitalize it according
to the capitalization rules for regular titles, and do not use a hyphen.
I know that Vice President Thompson assisted on the project.
He is asking, Mr. Vice President, about the work on the committee Dill.
We sent for the vice president to explain his actions.

CAPITALIZATION.35: Capitalize the titles of the departments that comprise the President's Cabinet,
including the name of the department and the word department when it stands alone.
The Department of the Interior is not involved.
I think that is a Treasury issue.
It is within Department policy.

CAPITALIZATION.36: Capitalize the titles of positions in the President's Cabinet, including the word
secretary when it stands alone.
The Secretary of State arrived for the meeting.
I spoke with the Secretary.
It is within the purview of the Secretary of Defense.

CAPITALIZATION.37: Capitalize the word cabinet when it refers to the advisory board to the President
of the United States.
The Cabinet met late into the night.
The meeting of the Cabinet was postponed.
He is anew member of the President's Cabinet.

CAPITALIZATION.38: Capitalize the word congress when it refers to the law-making body of the
United States.
He has been a member of Congress for 24 years.
There was a joint meeting of both houses of Congress.
The congress of delegates met ahead of the general meeting.

CAPITALIZATION.39: Capitalize the word senate and the word house when they refer to the law-
making bodies of the United States.
The Senate opposed the Dill.
He was a veteran member of the Senate.
The members of the Senate debated the bill.
She is a member of the House.
The House voted overwhelmingly for the bill.
The House amendment will now go to the Senate for approval.

CAPITALIZATION.40: Capitalize the word speaker when it refers to the person from the majority party
that heads the House of Representatives.
He is a member of the House and wants to be the Speaker.
The Speaker is currently a woman.
The bill was initiated by the Speaker of the House.

CAPITALIZATION.41: Capitalize senator and representative the way other titles are capitalized. That
is, capitalize them in front of the name as a title and in direct address, and do not capitalize them in
context.
I spoke with Senator Barnsdall and Representative Johnson.
He is asking, Senator, about the current bill.
The representative was spotted In the hallway.

CAPITALIZATION.42: Capitalize the names of the standing committees in the House and Senate.

He is a member of the Judiciary Committee.
The Committee on Ways and Means is meeting to consider the Dill.
I think the Finance Committee is responsible for that.

CAPITALIZATION.43: Capitalize the full, complete name of bills and acts.
It is part of the Taft-Hartley Act.
The Weyland Farm Appropriations Bill was enacted in June.
It is part of the Civil Rights Act of 1964.

CAPITALIZATION.44: Capitalize the word constitution when it refers to the constitution of the United
States.
It is in Article Ill of the United States Constitution.
The Constitution was written in Philadelphia.
The Constitution guarantees the right to bear arms.

CAPITALIZATION.45: Do not cap the word constitutional in general contexts.
We are looking for a constitutional amendment.
He teaches constitutional law.
Though it was not popular, the law was ruled constitutional.

CAPITALIZATION.46: Capitalize the names of the various sections of the United States Constitution.

We all had to memorize the Preamble to the Constitution when we were kids.
It is part of the Bill of Rights that we all enjoy.
I believe it is in Article Ill of the Constitution.

CAPITALIZATION.47: For the first ten amendments, write out the number and capitalize both the
number and the word amendment.
It is a Second Amendment right that he is relying on.
He took the Fifth as his answer to every deposition question.
It is a matter of preserving the First Amendment.

CAPITALIZATION.48: Capitalize the names of political parties, past and present, and the adjectives
that come from them.
The Republicans are in control.
she is a Democratic candidate.
Jefferson was against the Federalists.

CAPITALIZATION.49: Capitalize the words government and federal when they are parties to the
lawsuit.
The Government will prove this by a preponderance of the evidence.
He is going to be a Federal witness in an upcoming case.
At this time, the Government rests.

CAPITALIZATION.50: Capitalize the word governor when it stands alone in context but not the other
officers of the state and local governments.
I spoke with the Governor earlier in the day.
It is the responsibility of the comptroller of the state.
The mayor herself showed up at the site of the massive fire.

CAPITALIZATION.51: On the state level, capitalize the word constitution only when it is part of the full
title.
The Constitution of the State of California prohibits It.
It is a constitution that should be thrown out and written from scratch.
It is not in the state constitution.

CAPITALIZATION.52: Capitalize the names of the state and city legislative bodies when they are part of
the full name; otherwise, leave them lowercase.
She is a long-time member of the Los Angeles City Council.
The city council will vote on the controversial measure.
He is a member of the California Senate.
The senate form of the bill did not pass.
He is the senior member of the Orange County Board of Supervisors.
It was a difficult decision for the board of Supervisors

CAPITALIZATION.53: Capitalize the words city, county, and state when they are parties to the lawsuit
or when they refer to the specific entity.
Her paycheck comes from the City of Los Angeles.
Did that occur in the city of Los Angeles?
The State rests.
He lives in the state of California.

The County will prove it was not negligent.
I live near the county line.

CAPITALIZATION.54: Capitalize the names of the branches of the service, including the words
Armed Forces.
The Marines overran the position and took charge.
It is said that the Navy will also be involved.
He is an Army sergeant.

CAPITALIZATION.55: Capitalize the full names of groups, associations, committees, company,
organizations, et cetera.
The National Association for the Advancement of Colored People was involved.
She was a member of the Greater Cleveland Investment Group.
He was elected to the Heather Village Architectural Committee.

CAPITALIZATION.56: Do not capitalize the words group, association, committee, company,
organization, et cetera, when they stand alone.
His association was in charge of the fundraiser.
I did not consult that company at all in my research.
The committee voted to deny coverage.

CAPITALIZATION.57: Capitalize board of... when it is part of the full name of the organization but
generally not when it stands alone.
He is a member of the Meadows Board of Directors.
The board of directors voted to increase the dues.
The San Diego Board of Education will vote on that tonight.
I spoke to a board member about that.
She received the memo from the Edwards Foundation Board of Managers.
I spoke with members of the board of managers informally after the meeting.

CAPITALIZATION.58: Capitalize the names of people, whether real, fictitious, or personified.

I felt as if Santa Claus had just been there.
He is a relative of Marcos Hess. So he is not a John Doe in this case.
He expressed the idea that Father Time was catching up with him.

CAPITALIZATION.59: Capitalize the names of nationalities, languages, and races and the adjectives
that come from them.
It was in German, I believe, but his Austrian friend could read it.
He is of Spanish descent and has studied Latin.
We enjoyed the Danish pastry and the Belgian waffles.

CAPITALIZATION.60: Capitalize the specific names of geographic locations, including lakes, rivers,
oceans, mountain ranges.
He lives near Lake Placid and can visit New York City whenever he likes.
We stopped at the Grand Canyon and Zion National Park.
She resides where she can see the Rockies out her kitchen window.

CAPITALIZATION.61: Capitalize the names of locations such as cities and states and their nicknames,
buildings, parks, airports, train stations.
I reside in the Windy City, which lives up to its name much of the time.
The Empire State Building was unscathed in the thunder and lightning storm.
We went from Union Station to Baltimore-Washington Airport.

CAPITALIZATION.62: Capitalize recognized references to specific areas that do not necessarily contain
a proper noun.
We flew to the Bay Area for a short vacation.
the San Francisco area in California
The glory days of the Miracle Mile have faded.
a segment of Wilshire Boulevard in Los Angeles
The President delivered the address from the Rose Garden.
an area of the White House

CAPITALIZATION.63: Capitalize the word God when it refers to a divine being but often not in slang
expressions nor in the plural.
He has a strong belief in God.
That house is painted a god-awful color.
There are many gods in his tribal religion.

CAPITALIZATION.64: Capitalize all references to a supreme being.

He is sustained by his belief in a Higher Power.
They called upon Allah.
She believes the Holy Spirit got her through the tragedy of the accident.

CAPITALIZATION.65: Capitalize pronouns that refer to a divine being.
God is coming, and She is very upset.
My sister believes in a Supreme Being and knows that He is protecting her.
My belief in Him sustains me.

CAPITALIZATION.66: Capitalize the names of all religions and their followers.
She follows the teachings of Zen Buddhism.
He converted to Christianity and is now an Episcopalian.
They grew up as Mormons in a small Utah town.

CAPITALIZATION.67: Capitalize the names of religious buildings only when they are a part of the
proper noun.
We live across the street from Temple Akiba.
We live across the street from a Jewish temple.
He attends Holy Nativity Episcopal Church.
He attends an Episcopal church in our neighborhood.
I drove by King Fahad Mosque just before it happened.
I drove by the Islamic mosque just before it happened.

CAPITALIZATION.68: Capitalize the word church only when it is part of a proper name or when it
refers to the entity itself.
I live near St. Jerome Catholic Church.
The Catholic Church opposes abortion.
There is a Catholic church on that corner.

CAPITALIZATION.69: Capitalize the names of books regarded as holy books and other references from
sacred works.
My goal was to read the Bible from cover to cover.
He is very familiar with the Quran.
He is well schooled in the Torah.

He has memorized the Nicene Creed.
The Lord's Prayer was recited in Spanish.
The Beatitudes are always read at that service.

CAPITALIZATION.70: Capitalize references to holy persons and historical religious events.
It is part of the story of John the Baptist.
The King of the Jews title provoked controversy in that age.
I had the privilege of meeting with the Dalai Lama.
We regard the Exodus as a major event in our history.
It is an artistic rendering of the Resurrection.
It is part of the story of the Last Supper.

CAPITALIZATION.71: Capitalize and write out the word reverend in front of the name. Capitalize other
religious titles in front of the name but not after the name.
The Reverend Peter Rood joined the panel discussion.
We spoke with Peter Rood, the rector of the church.
The document was written by Rabbi Jason.
I referred her to the rabbi.
It was written to Deacon Margaret.
I spoke with the deacon later in the day.

CAPITALIZATION.72: Do not capitalize the words sun and moon in general contexts.
We call it "June gloom," and we haven't seen the sun all month.
The moon, as it rose over the mountains, was bright orange.
The sun and moon are often used as symbols of the occult.

CAPITALIZATION.73: Capitalize the word earth only when it is mentioned with other planets or when
it is personified.
It concerned Jupiter, Earth, Neptune, and Venus.
We are in desperate need of saving Mother Earth.
It is In orbit around the earth.

CAPITALIZATION.74: Capitalize the names of the planets, stars, and constellations.

Could there have been life on Mars?
The star Rigel is part of Orion.
I believe it is found in Ursa Major.

CAPITALIZATION.75: Capitalize a title in front of the name.
We spoke with Detective Ramirez at the scene.
It is common knowledge that Representative Mills is set to resign.
Do you know when Professor Stone has office hours?

CAPITALIZATION.76: Capitalize a title when it is used alone as direct address.
I want to know, Sergeant, exactly what time you arrived at the house.
Do you think, Senator, you could give us a short version of your opinion?
You have testified, Doctor, that the cause of death was suffocation.

CAPITALIZATION.77: Do not capitalize a title when it is used by itself in the context of a sentence.

There is a lead sergeant assigned to the case.
The senators were In conference regarding this matter.
I met with the doctor on several occasions.

CAPITALIZATION.78: Do not generally capitalize titles that come after names.
I listened to Margaret Sands, president of our local chapter.
We were in a meeting with Thomas Little, mayor of Indianapolis.
The decision came from Susan Lilly, chairman of the board.

CAPITALIZATION.79: Capitalize any word that has Mr., Mrs., Ms., or Miss in front of it.
Would you please, Ms. Court Reporter, read that back to us.
I know that Ms. District Attorney is going to object.
Would Mr. know-It-All please be quiet.

CAPITALIZATION.80: Capitalize the first and the last word of all printed, published, and artwork titles,
whether italicized, underlined, or quoted. Then capitalize all other words in a title except short
prepositions; short conjunctions; and the articles a, an, and the.

He read Gone with the Wind.
He read "Gone with the Wind."
I enjoyed the article "What Has Become of Them?"
He commented on the theme in the movie /n the Heat of the Night.
He commented on the theme in the movie "In the Heat of the Night."

## THE NUMBER QUESTION

NUMBER.1: In general, use words for the numbers one through ten and figures for the numbers 11 and
up.
I believe we used seven in the operation.
It may have been two or three months later that I talked with him again.
She reportedly had ten siblings still living at home.
He sent me 28 before the beginning of May.
There were 42 moving parts to that machine.
He says he processed 400 each day.

NUMBER.2: Use "over ten/under ten" for ordinal numbers as well as cardinal numbers.
There were 30 people in the seventh row.
There were five people in the 27th row.
I was fifth in the line and still waited over a half hour.
She was 14th out of a class of 500.
I think it is the seventh printing of the book.
This must be the 40th time that he has changed his mind.

NUMBER.3: Always use figures for numbers in the thousands. With some exceptions, also use a comma
for figures in the thousands.
We lost 14,250 cartons in the train disaster.
There were 22,000 people in attendance.
We usually received them in lots of 2,500.

NUMBER.4: Do not use a comma in figures for things like a year or a serial number (unless there
happens to be a comma in the number as created).

In the year 1200 it had not been discovered.
Her great-grandmother was born in 1802 and lived to be 102.
It is No. 45898 in the sequence.

NUMBER.5: Beginning with the number 1,000,000, use figures or use the figure and the word million,
billion, trillion, et cetera.
There are 3,000,000 children living in poverty in that country.
There are 3 million children living in poverty in that country.
Health care costs topped 50,000,000,000 last year.
Health care costs topped 50 billion last year.
The national debt was 2,000,000,000,000 and counting.
The national debt was 2 trillion and counting.

NUMBER.6: Use the same form for like numbers, for those that measure related elements.
There were 7 men and 12 women on the committee.
I sent 5 at the beginning. They immediately ordered 22 more.
There were 575,000 to start and 2,000,000 the next year.

NUMBER.7: When some numbers are under ten in a sentence and others are over ten and they measure
like items, use figures for all the numbers.
The order was for 9 hamburgers and 12 hotdogs.
She added 8 for her son and 16 for his friends.
At least 8 more are needed for today and 14 more for tomorrow.

NUMBER.8: Apply the consistency rule to numbers that occur in the same sentence, in the same
conversation, and/or in the same general area of the transcript.
Q How many did you order that day?
A It was standard to order 2 or 3 a day.
Q And is that what you did that Friday?
A No. That day we ordered 13.
Q Why did you order 13?
A Because our supply had been depleted. We were down to 8.

NUMBER.9: Use the consistency rule for numbers in a series even when the numbers measure different
things.

We bought 18 sodas, 9 sandwiches, and 7 bananas.
There were 12 adults, 2 teenagers, and 19 kids.
We donated 2 lamps, 4 chairs, and 15 bags of clothing.

NUMBER.10: Consider putting an incomplete number that is over ten in figures and putting a hyphen
before it or after it to show that there is more to the number.
We sold the property in the desert for 500-.
It was in the year 19- -- oh, I am not sure.
I made 7- on that job.
I think it is 024534 on the -- no. It is -33.
It is 5476 Benson Avenue or -/8 Benson Avenue.
The number is 800-424-3355. Oh, wait. It is -66 on the end, I think.

NUMBER.11: When a number is made indefinite by the addition of words like some, something, some
odd, hyphenate these words to the end of the number whether it is in words or figures.
There were 70-some on order.
I know that 50-odd people were there.
He paid 30-something.

NUMBER.12: When a number is preceded by words like approximately, close to, nearly, simply
transcribe the word followed by the number in correct form according to "over ten/ under ten."

I saw approximately four doctors for this problem.
It was Close to 50, I think.
There were around 200 people in attendance.

NUMBER.13: When someone says "a dollar" or "a hundred" or "a thousand" or "a million," write it out.

It was over a million dollars that we invested in that.
I think it was a hundred fifteen.
It is a little over a dollar more.

NUMBER.14: Write out in words the numbers 1-99 when they begin a sentence.
Fifty-nine of us were involved in the project.
Seventeen were required each day.
Forty-three were defective and had to be returned.

NUMBER.15: Use figures for the numbers 100 and above when they begin a sentence.
782 were delivered at the beginning of January.
1969 was the year of the first moon landing.
355,000 were sold for the year.

NUMBER.16: Use figures for all dates.
Kennedy was assassinated November 22, 1963.
she called on the 14th.
I believe it is scheduled for August the 9th.

NUMBER.17: Use figures for military dates without any commas.
It occurred 7 December 1941.
The tragedy was on 11 September 2001.
Call before 10 July.

NUMBER.18: When the word first refers not to the specific date but to the first part of the month, write
out the word first.
I will be there for a week the first of March.
We will be gone five days the first of May.
He wants it over a period of several days during the first of October.

NUMBER.19: Use figures with a colon for the times of the day and figures, a colon, and ciphers for those
times that are on the hour.
Be there no later than 7:30.
We were expected to arrive at 8:00 on the dot.
The train leaves at 3:00 sharp.

NUMBER.20: If the word o'clock is said, transcribe it, and leave the time in time figures.
My appointment is for 3:00 o'clock.
I will be there at 7:00 o'clock.
9:00 o'clock is too early for me to make it.

NUMBER.21: If A.M. or P.M. is said, transcribe it, and leave the time in figures.

The appointment was for 4:20 P.M.
He left his house at 5:30 A.M.
She arrived at my office at 9:30 A.M.

NUMBER.22: For a 24-hour time system as used in the military, use four figures with no punctuation.

We arrived at 1800 hours.
He was to be there at 1600.
It closed at 1530.

NUMBER.23: For amounts under one dollar, when the word cents is said, follow "over ten/under ten"
for the number, and write out the word cents.
The day of the five-cent stamp is gone forever.
They were just over 60 cents each in lots of 5,000.
one was shortchanged by just 15 cents.

NUMBER.24: For even amounts of one dollar and up, use figures with the dollar sign for the word
dollars if said.
I was told it would be just $3 for each one.
He paid $72 for the ticket.
I thought $400 was too much to pay for that.

NUMBER.25: Make the dollar amounts that measure "like" items in the same area of the transcript
consistent.
Incorrect: It was 59 cents for the blue and $1.34 for the others.
Correct: It was $.59 for the blue and $1.34 for the others.
Incorrect: She sent a check for $12.75 for the first one and $80 for the other.
Correct: She sent a check for $12.75 for the first one and $80.00 for the other.
Incorrect: It was $657,000 in June and $3 million a year later.
Correct: It was $657,000 in June and $3,000,000 a year later.

NUMBER.26: Put all addresses in figures with the exception of the house number one.

He lives at 15 Bonner Road.
I just moved to 8 Connor Street.
She lived at One Park Place.

NUMBER.27: Use "over ten/under ten" for street names that are numbers.
He lives on Second Avenue.
We passed 13th Street, and I knew we had gone too far.
I was told it was somewhere on Ninth.

NUMBER.28: Put all percentages into figures, and write out the word percent. Do not hyphenate the
percentage used as an adjective.
It was a / percent increase.
We will need a raise of 3 percent.
It is up Dy 35 percent in just one year.

NUMBER.29: Use figures for all decimal amounts.
Production is up by a mere .2 this month.
How do you explain the 14.5 drop in the rates?
I did not know about the 3.5 percent additional amount.

NUMBER.30: Use figures for all sequential references.
It is page 15, beginning on line 5.
I think it is discussed in Chapter 8 of the book.
Go down to paragraph 3.

NUMBER.31: If the ordinal precedes the word that states what it is, use "over 10/under 10."
I did not answer the eighth question.
I did not answer Question 8.
The 12th chapter will be the last.
Chapter 12 will be the last.
This is the fourth exhibit on the same topic.
This is Exhibit 4 and is on the same topic.

NUMBER.32: Abbreviate the word number when it precedes a figure except at the beginning of a
sentence, where it should be written out.
I did not see No. 4 in the list of documents that I reviewed.
She wrote No. 356 to her landlord.
Number 7 is the one I want to focus on now.

NUMBER.33: Put heights in figures when said with the words feet and inches, which are written out.

He is 5 feet 11 Inches.
She is 6 feet even.
I judge her to be about 5 feet 3.

NUMBER.34: When the words feet and/or inches are not said, write out the numbers in words with no
punctuation between them OR put them in figures with a hyphen between them.
She is five three.
She is 5-3.
He is five eleven.
He is 5-11.
He measures a little over six eight.
He measures a little over 6-8.

## THE APPOSITIVE

APPOSITIVE.1: When a noun appositive immediately follows the word it renames and is essential to
define that word, use no punctuation around it.
My neighbor Sam was driving the car at the time.
She said she had purchased the meth from her friend Harrison.
The medication Valium was used for sleep.

APPOSITIVE.2: When a noun appositive immediately follows the word it renames and is nonessential
because the word it renames is already defined, use a comma in front of the appositive or commas
around the appositive if it is in the middle of the sentence.

It resulted in minor damage to my car, the Prius.
My 21-year-old daughter, Justine, was driving the car.
He told me that Marianne, my oldest sister, was set to inherit everything.

APPOSITIVE.3: When a noun appositive is not right after the word it renames but is "removed" from it,
in most cases, use a comma in front of it or a pair of commas around it if it is in the middle of the
sentence.
I believe I spoke with the CEO at that time, Cathy Nguyen.
I spoke to the surgeon at the hospital, Dr. Aurelio, just after the surgery.
It was Bonnie White that was in charge, a CPA, of Keeping the statistics.

APPOSITIVE.4: When a noun appositive is very far removed from the word it renames, use a dash in
front of it or a pair of dashes around it if it is in the middle of the sentence.
We tried to join the party later in the evening after the conference ended -- Mary and I -- In
order to meet and get to know her sister's fiance.
The bank manager did not get involved in the transaction In question in this suit until June
- George Gerson -- and was not very helpful when he did.
The president of the company where my mother worked for 25 years before retiring two
years ago -- Ms. Wright -- led the discussion.

APPOSITIVE.5: When a noun appositive to the subject of the sentence comes after the sentence has
finished, use a dash before the appositive.
They tried to find out what we were doing in the lab -- Dr. Ray and his assistant.
The actor claimed he did not sign the contract -- Taylor Hemmings.
We were there -- my wife and I.

APPOSITIVE.6: When a noun appositive precedes the word it renames, use a dash after the appositive.

The passenger in the car -- he wasn't visible from my viewpoint.
Exhibit 5 -- she sent this email to you in June of last year.
The watch I am holding in my hand -- were you wearing this that night?

APPOSITIVE.7: When a noun clause appositive follows immediately the noun it renames and is
essential to define that word, use no punctuation.
The fact that he left early daily is of interest to us here.
The information that he was in the vicinity might be helpful to know.
The statement that he had borrowed money from her is important in the case.

APPOSITIVE.8: When a noun clause appositive follows immediately the noun it renames and is
nonessential, use a pair of commas or a pair of dashes to surround the clause.
That issue, whether or not he tampered with the books, is in question.
That issue -- whether or not he tampered with the books -- is in question.
That question, why Ne ald not simply stop and explain, has not been resolved.
That question -- why he did not simply stop and explain -- has not been resolved.
That reason, how she was able to fool them for so long, is necessary to know.
That reason -- how she was able to fool them for so long -- is necessary to know.

APPOSITIVE.9: When a noun clause appositive is removed from the word it renames, use a pair of
dashes around it.
The thing we are talking about here -- when exactly you left the house that morning to go
to work -- is not clear to me.
I want to ask a few questions about a discrepancy that I perceive in the answers you
have given -- how far away you were at the exact moment of the collision -- and to
try to see whether we can clear that up.
she had worked for us for a number of weeks before any issues or problems came up -
that she would arrive late, that she would make personal phone calls -- such that
they interfered with her work.

APPOSITIVE.10: When a noun clause appositive renames the subject and comes after the sentence has
finished, use dash before it.
it just wasn't fair -- that she always got everything she wanted from him.
That's what I believed -- that I would be fired first.
That's what's important -- that you call every day first thing in the morning.

APPOSITIVE.11: When a descriptive adjective follows the noun it modifies, use a comma in front of the
adjective or a pair of commas around it if it is in the middle of the sentence.
As I came around the corner, I noticed a car, reddish in color.
There was a girl, tall and blond, who seemed to be in charge.
Her signature, rather hard to read, was at the bottom.

APPOSITIVE.12: When a descriptive adjective begins a sentence and therefore precedes the noun it
modifies, put a comma after it before the main sentence begins.

Bright chartreuse green in color, the car stood out on the highway.
Triumphant, the company president made the announcement.
Far from confident, / entered the courtroom.

APPOSITIVE.13: When a participle immediately follows the noun it modifies and is essential to define
that word, use no punctuation.
The man wounded in the gunfight recovered.
It had to do with the nurse standing at her bedside.
The suspect driving the car was captured.

APPOSITIVE.14: When a participle immediately follows the noun it modifies and is not essential to
define that word, use a comma in front of the participle or commas around it if it comes in the middle of
the sentence.
My only brother, wounded in the gunfight, recovered well.
She agreed with her husband, sitting at her side.
I sent it to my 30-year-old daughter, living in New York at the time.

APPOSITIVE.15: When a participle is removed from the word it modifies and is farther down the line in
the sentence, in most cases, use a comma in front of it or surround it with commas if it is in the middle of
the sentence.
The bank stored the records in the vault, wanting to protect them.
Henry yelled at her frequently, upset about her behavior.
She was standing in the doorway, yelling at me as I walked away.

APPOSITIVE.16: When a participle begins a sentence, either alone or as a part of a participial phrase,
always use a comma after it before the main sentence begins.
Sobbing, she ran from the room.
Having finished the project, they all went out to celebrate.
Startled by the news, we huddled around the radio.

APPOSITIVE.17: When an appositive of any kind needs commas around it and then also has
punctuation inside of it, change the commas that surround it to a pair of dashes.
The vitamins he is taking - E, C, and A -- are contained within this medication.
The classes -- math, science, and English -- were too hard for him.
The months those payments were due -- May, June, and July -- were tough.

## THE ELLIPSIS

ELLIPSIS.1: Use the ellipsis to show that words in the original quote have been omitted.
"The responsibility for this rests with...the moving party."
"...in effect for 30 days...from the date of enactment."
"This contract will be in effect...for four years."

ELLIPSIS.2: When the ellipsis shows an omission that occurs at the end of a sentence, use a fourth
period to indicate the end of sentence.
"It will be in force for the duration...."
"The home will remain in the possession of the wife...."
"Ask not what your country can do...."

ELLIPSIS.3: When the witness is not interrupted but trails off, use the ellipsis if you want to show a
difference between using the dash for being interrupted and the ellipsis for trailing off.
A I was on the edge of It and...
A They all did it at the same time; so...
A We were just...

## THE PARAGRAPH

PARAGRAPH.1: Paragraph when the subject matter of the material changes.
A Since it was the middle of the winter, it was very dark and cold; furthermore, it was
late at night. I did not remain there for long because of the weather.

She had been there for quite some time. I don't know how long.
A We were traveling eastbound at the time of the collision. Since it was early
morning, we were looking directly into the sun.

My brother was driving at the time.

PARAGRAPH.2: Paragraph when the person speaking changes.
A She said, "I have never seen him before."
I said that I did not believe her.
she said, "I swear to you that I do not know him."
I said, "Okay. Explain the picture that shows the two of you."

PARAGRAPH.3: Paragraph when the person being addressed changes.
THE COURT: I will sustain your objection.
Please do not answer the question.
Please rephrase your question.
A I was with several people that can verify that I --
Would you read that question back to me, please.

## THE PARENTHETICAL

PARENTHETICAL.1: Always surround a parenthetical with punctuation, wherever it appears in the
sentence.
When, at any rate, did you complete this form?
Ms. Reinart didn't attend that meeting, though.
In fact, we did have a disagreement over that issue.

PARENTHETICAL.2: Put a period after a strong interjection.
(Note that, in an effort to not offend anyone, there is only enough of the "four-letter" word for it to be
recognizable.)
Damn. I did not bring that with me.
When did he say that? S**t.
F**k. You keep asking me the same question.

PARENTHETICAL.3: Surround a mild interjection with punctuation, usually commas.
We were, well, really busy with, oh, several people at once.
It was after, say, we got home and took, well, 20 of them.
If he wants to do that, why, I don't really care.

PARENTHETICAL.4: Surround a neutral remark with punctuation, usually commas, wherever it occurs.

There is no issue in this area, in my judgment.
Where, according to the eyewitness, was she standing?
As you see it, what factors were involved?

And, sitting here today, do you have an opinion as to why?
It was a Friday, best of my recollection here today.
Off the top of your head, how much do you think he owed you?

PARENTHETICAL.5: Surround numbers and letters to denote items in a list with punctuation, usually
commas.
They are, one, overpriced and, two, shabbily made ana, three, inferior to others.
It was, first, too expensive and, second, too much work and, last, too boring.
I left, one, because they would not raise my pay and, two, because I felt I was carrying
the whole load and, three, because no one was helping.

PARENTHETICAL.6: When the parenthetical is followed by a fragment, use commas around the
parenthetical.
I am sure it was a large car, that is, a sedan.
He was in desperate need of a specialist, namely, a Surgeon.
she showed me the selections, e.g., the carpet samples.

PARENTHETICAL.7: When the parenthetical is followed by a complete sentence, put a semicolon in
front of the parenthetical and a comma after it.
I am sure it was a large car; that is, it was a sedan.
He was in desperate need of a specialist; namely, he needed a Surgeon.
She showed me the selections; e.g., I Saw carpet samples.

PARENTHETICAL.8: When the parenthetical is followed by a list, put a colon in front of the
parenthetical and a comma after it.
We toured four cities: that is, Reno, Las Vegas, Phoenix, and Tucson.
I sent it to them immediately: i.e., Jim, Bill, and Tony.
The tax errors were in several categories: e.g., supplies, travel, gifts.

PARENTHETICAL.9: When the parenthetical and the appositive are at the end of the sentence and the
appositive renames something at the beginning of the sentence, put a dash in front of the parenthetical
and a comma after it.

I had a major headache when she called me into her office and was really having trouble
concentrating -- that is, a migraine.
He has been accused of a crime that is all too common in our society today -- namely,
grand theft auto.
That is exactly what we had discussed and settled on -- that is, that he would pay off the
loan in full by March 1.

PARENTHETICAL.10: When the parenthetical is in the middle of the sentence, put a dash before the
parenthetical and a comma after it, and put a dash after the appositive.
I saw him early in the day -- that is, around 7:30 -- and did not see him again.
There were three -- e.g., red, pink, and salmon -- that she particularly liked.
I had several -- i.e., John, Joe, or Harry -- that I was going to recommend.

PARENTHETICAL.11: When a question is followed by a parenthetical, which is then followed by a
second question or clarifying information, put a question mark after the question. Put a comma after the
parenthetical and a period or a question mark at the end of the second element, depending on the
intonation you hear as it is said.
What time did this occur? That is, what time did he call?
Do you know the name he was using? In other words, his alias(?) OR (.)
Did he show you the line? For example, some of the power tools(?) OR (.)

## THE SERIES

SERIES.1: When every item of the dependent series is linked by a coordinate conjunction, use no
comma before any of those conjunctions.
CC _____ CC _____ CC _____ CC (CC = coordinate conjunction)
...and Bob and Mark and Raul and Peter...
...In the theater or on the street or in the car...
...If he is there and if he has time and if he wants to talk...

SERIES.2: When there are no conjunctions between any items in the dependent series, use a comma to
separate each item.

...Bob, Mark, Raul, Peter...
...In the theater, on the street, In the car...
...if he is there, if he has time, if he wants to talk...

SERIES.3: When there is a conjunction before the last item in the dependent series and in no other
place and that conjunction links two distinct items, use a comma between each item in the series and
before the conjunction for the final item in the series.
The Dodgers, Red Sox, or Mets are predicted to win.
I spoke with the attorneys, the judge, and the witnesses.
He was doing 50, 55, or 60, in my opinion.

SERIES.4: When there is a conjunction before only the last item in the dependent series and that
conjunction links two items that form one unit, do not use a comma before the conjunction.
It was given to accounting, human resources, research and development.
I sent It to Jan and her husband, Barry, James, Ralph and his wife.
We ordered dry toast, coffee, bacon and eggs.

SERIES.5: When there are conjunctions in some places and not in others between the items in the
dependent series, use the rules SERIES 1, SERIES 2, and SERIES 3 to punctuate the elements: a comma
where there is no conjunction, no comma where there is a conjunction, a comma before the last
conjunction in the series.
I saw Bob, Tern, Marilyn and Ashley, Joe, Peter, and Maggie.
The bills were $75 and $975 and $30, $560, $370, $130, and $685.
He called at 4:15, 4:30, 5:00 and 5:15, 5:30, and 6:00.

SERIES.6: Ina series where separating punctuation is needed between the items in the series but where
one item has internal punctuation -- that is, punctuation within an item in the series -- use a semicolon
to separate each item in the series.
I had salad; steak, which was tough; and a baked potato.
He lived in Rome, Georgia; Paris, Tennessee; and Palestine, Texas.
They were an Embassy Suites, which was the best; a Hilton; and a Marriott.

SERIES.7: Separate each item of the series with the same type of punctuation.

Incorrect: He sent the correspondence to Miller, Hubbell, Henderson, who is the senior
administrator; Ruiz, Cheng, and Hartman.
Correct: He sent the correspondence to Miller; Hubbell; Henderson, who is the senior
administrator; Ruiz; Cheng; and Hartman.

SERIES.8: When numbers/letters enumerate the items of a series, make the number a word rather than
a figure, and write out the word number when said. Capitalize the letters.
He needs, one, the tax records and, two, the employment records.
There were, A, cars: B, buses; and, C, trucks.
I donated, number one, $400 to the church; number two, $300 to a veterans
organization; and, number three, 5200 to local jaw enforcement.

SERIES.9: When there is a conjunction between each item of the series, put commas around the
parenthetical numbers/letters used to enumerate and no punctuation between the items.
I had the responsibility for the personnel and the maintenance and the storage ana the
cleanup.
I had the responsibility for, one, the personnel and, two, the maintenance and, three, the
storage and, four, the cleanup.
We were sent a bill and a reminder and a threat.
We were sent, first, a bill and, second, a reminder and, third, a threat.
She knows that he was there and that he did not talk to anyone and that he then left to
go home.
She Knows, A, that he was there and, B, that he did not talk to anyone and, C, that he
then left to go home.

SERIES.10: When there are no conjunctions between any items of the series, put commas around the
parenthetical numbers/letters, and change the commas between the items 1n the series to semicolons.

The three nominees were Hodges, Miller, Nagano.
The three nominees were, one, Hodges; two, Miller; three, Nagano.
I was taking the heart medicine, the stuff to sleep, the Viagra.
I was taking, first, the heart medicine; second, the stuff to sleep; last, the Viagra.

He always said he would outlive her, he would have lots of money, he would leave it all to
charity.
He always said, A, he would outlive her; B, he would have lots of money; C, he would
leave it all to charity.

SERIES.11: When the only conjunction is before the last item of the series, separate the items in the
series with semicolons, and put commas after each parenthetical number.
We made major sales in February, June, and August.
We made major sales in, one, February; two, June; and, three, August.
I sent inquiries to Sawyer, Bryce, and Nowalski.
I sent inquiries to, one, Sawyer; two, Bryce; and, three, Nowalski.
We had researched homes in Seattle, Tacoma, and Portland.
We had researched homes in, A, Seattle; B, Tacoma; and, C, Portland.

## THE TAG CLAUSE

TAG CLAUSE.1: Use a question mark at the end of any sentence that contains a tag clause.
He was speaking, wasn't he, about your performance?
The copyright had expired, hadn't It?
The account needed two signatures; is that correct?

TAG CLAUSE.2: When a tag clause echoes the words of the sentence and is at the end of the sentence
use a comma before it and a question mark after it.
The boss was not always on the premises, was he?
The defendant had been seen earlier in the day, hadn't he?
1am correct in assuming she was fired, am I not?

TAG CLAUSE.3: When a tag clause echoes the words of the sentence and is in the middle of the
sentence, surround the tag clause with commas, and put a question mark at the end of the sentence.

Noah was treading, was he not, on dangerous ground?
The library didn't have responsibility, did it, for the program he initiated?
I am correct, am I not, in assuming that to be true?

TAG CLAUSE.4: When the tag clause is at the end of the sentence and contains any form of the words
right, true, or correct, use a semicolon in front of the tag clause and a question mark after.
It arrived just after 9:00; isn't that right?
They stayed later than you would have wanted; is that correct?
You had a grudge against him; is that true?

TAG CLAUSE.5: When direct address is after the tag clause at the end of the sentence, use a semicolon
before the tag clause, a comma for the direct address, and a question mark at the end of the sentence.

You attended that meeting without your attorney; is that correct, sir?
His daughter was also paid by the company; right, Mrs. Hanover?
The check bounced: isn't that correct, Ms. Williams?

TAG CLAUSE.6: When the tag clause is in the middle of the sentence and contains any form of the
words right, true, or correct, it takes a pair of dashes around it, a question mark after it inside the
dashes, and a question mark at the end of the sentence.
They were sent via Federal Express on Friday -- right? -- and were delivered the very
next day?
The first recording was purchased by your company -- is that correct? -- immediately and
then was released to the public?
She had worked in the IT department until -- is that right? -- she went on maternity leave
In April?

TAG CLAUSE.7: When the tag clause contains any form of the words right, true, or correct and is in the
middle of the sentence AND clarity of reading and bulkiness is a consideration, use commas around the
tag clause and a question mark at the end of the sentence.
Q He called you - right? -- on Friday?
He called you, right, on Friday? Q
Q You were -- is that correct? -- at the meeting?
Q You were, is that correct, at the meeting?

TAG CLAUSE.8: Use a period before any other element that would seem to be a tag clause but does not
contain the words right, true, or correct.

You had given it your best effort. Is that what you are saying?
She was wearing dark colors and a baseball hat. Is that accurate?
Ms. Nguyen always did a great job. Yes?

## WHERE NOT TO PUT PUNCTUATION

NO PUNCTUATION.1: Do not put a single separating comma after a coordinate conjunction: and, but,
or, nor.
Incorrect: But, you have no proof of that; correct?
Correct: But you have no proof of that; correct?
Incorrect: And, I haven't had a chance to do that.
Correct: And I haven't had a chance to do that.
Incorrect: Or, you will have to make the decision.
Correct: Or you will have to make the decision.

NO PUNCTUATION.2: Do not put a single separating comma after a one-syllable conjunctive adverb:
so, thus, hence, then, still, yet, plus.
Incorrect: It was impossible; so, I had to just walk away.
Correct: It was impossible; so I had to just walk away.
Incorrect: Still, there was little he could do to change the situation.
Correct: Still there was little he could do to change the situation.
Incorrect: Yet, the insurance company had not fulfilled its obligations.
Correct: Yet the insurance company had not fulfilled its obligations.

NO PUNCTUATION.3: Do not put a single separating comma between the subject and the verb.

Incorrect: That man that was hired to defend her against the charges that were brought as a result
of the accident that occurred near her home on New Year's Eve, turned out to
be incompetent.
Correct: That man that was hired to defend her against the charges that were brought as a result
of the accident that occurred near her home on New Year's Eve turned out to
be incompetent.

Incorrect: What you will need to finish this project that was started by the company late last year in
response to an issue with costs, remains unknown.
Correct: What you will need to finish this project that was started by the company late last year in
response to an issue with costs remains unknown.
Incorrect: Whether we met on Monday, June 5, or Thursday of that week with Pearson, the CEO,
about the issues with the bank and the accounts that are out of balance, Is not
something I remember.
Correct: Whether we met on Monday, June 5, or Thursday of that week with Pearson, the CEO,
about the issues with the bank and the accounts that are out of balance is not
something I remember.

NO PUNCTUATION.4: Do not put a single separating comma between an adjective and the word it
modifies.
Incorrect: He had a long, hard, boring, day.
Correct: He had a long, hard, boring day.
Incorrect: She is an interested, engrossed, viewer.
Correct: She is an interested, engrossed viewer.
Incorrect: He paled when he saw the burly, muscular, man walking toward him.
Correct: He paled when he saw the burly, muscular man walking toward him.

NO PUNCTUATION.5: Do not put a single separating comma ora colon between a preposition and its
object.
Incorrect: We sent letters to, Rodriguez, Sanchez, and O'Dell.
Incorrect: We sent letters to: Rodriguez, Sanchez, and O'Dell.
Correct: We sent letters to Rodriguez, Sanchez, and O'Dell.
Incorrect: I left the message for, Stephanie and Michael.
Incorrect: I left the message for: Stephanie and Michael.
Correct: I left the message for Stephanie and Michael.
Incorrect: We covered it for, Helena, Maria, and Christine.
Incorrect: We covered it for: Helena, Maria, and Christine.
Correct: We covered it for Helena, Maria, and Christine.

NO PUNCTUATION.6: Do not put a single separating comma or a colon between the verb and its direct
object.

Incorrect: Jan learned after a while, his name and address.
Correct: Jan learned after a while his name and address.
Incorrect: We decided later, to go into the office to talk.
Correct: We decided later to go into the office to talk.
Incorrect: I did not know at the time, whether she would be able to continue.
Correct: I did not know at the time whether she would be able to continue.

NO PUNCTUATION.7: Do not put a single separating comma or a colon between a verbal -- -ing, -ed, or
to plus a verb -- and the word that completes it.
Incorrect: The package she sent arrived today, containing: tax records and reports.
Correct: The package she sent arrived today, containing tax records and reports.
Incorrect: I want to include: his wife's affidavit and his deposition testimony.
Correct: I want to include his wife's affidavit and his deposition testimony.
Incorrect: I spent the morning researching, the applicable cases and the court decisions.
Correct: I spent the morning researching the applicable cases and the court decisions.

NO PUNCTUATION.8: Do not put a single separating comma or a colon between the verb and the
predicate nominative.
Incorrect: The names are: Miller, Manson, and Morgan.
Correct: The names are Miller, Manson, and Morgan.
Incorrect: She has been, secretary, vice president, and president.
Correct: She has been secretary, vice president, and president.
Incorrect: That house is, a real bargain.
Correct: That house is a real bargain.

NO PUNCTUATION.9: Do not put a single separating comma in compound dependent construction,
that is, when a coordinate conjunction joins elements that cannot stand alone to express a complete
thought.

Joining verbs = no comma
Incorrect: The office manager handled that, and did a good job.
Correct: The office manager handled that and did a good job.
Example marked correct in the source but inconsistent with the no-comma rule: I saw her early, but didn't see her again that day.
Correct: I saw her early but didn't see her again that day.
Incorrect: The bank foreclosed, but didn't find a new buyer for the house.
Correct: The bank foreclosed but didn't find a new buyer for the house.
Joining completer words = no comma
Incorrect: The names are Jonas Kent in accounting, and Jim Hertz in human relations.
Correct: The names are Jonas Kent in accounting and Jim Hertz in human relations.
Incorrect: He did not know whether to tell her at all, and what exactly to say.
Correct: He did not know whether to tell her at all and what exactly to say.
Incorrect: Leaving the house, or coming out of work, she needs to be more aware.
Correct: leaving the house or coming out of work, she needs to be more aware.
Joining two prepositional phrases = no comma
Incorrect: She remained unimpressed by Ray Ordonez, or by his entourage.
Correct: She remained unimpressed by Ray Ordonez or by his entourage.
Incorrect: You will find it across the street, and down the block.
Correct: You will find it across the street and down the block.
Incorrect: It was always parked in the garage, or near the front door.
Correct: It was always parked in the garage or near the front door.
Joining dependent clauses = no comma
Incorrect: If Mr. Handel had been there, and if he had been aware of the situation, he would
have spoken to her regarding her behavior.
Correct: If Mr. Handel had been there and if he had been aware of the situation, he would have
spoken to her regarding her behavior.

Incorrect: I was In agreement because they hadn't done the due diligence, and because they did
not have all the details.
Correct: I was in agreement because they hadn't done the due diligence and because they did
not have all the details.
Incorrect: The company had to be sold after the major account was lost, and after the president
absconded with the funds.
Correct: The company had to be sold after the major account was lost and after the president
absconded with the funds.

## WORDS THAT NEED A SPECIAL LOOK

THE WORDS (AL)THOUGH.1: When although or though begins an adverb clause that is at the end of
the element it modifies into and the adverb clause serves as a simple modifier, use no punctuation before
the adverb clause.
She encouraged us to leave (although she intended to stay).
Although...stay is an adverb clause modifying leave.
They were living in a rented apartment (although they owned a home in the area).
Although...area is an adverb clause that modifies were living.
He wanted us to cash the check (though there was no money in the account).
Though...account is an adverb clause that modifies to cash.

THE WORDS (AL)THOUGH.2: When although or though begins an adverb clause that is at the end of
the element it modifies into and the adverb clause expresses more a personal opinion or seems unrelated
to the content of the main clause, use a comma before the dependent clause.
she decided to marry him, (although it makes no sense to anyone in the family).
The account was to pay interest, (though I never saw a penny of it).
He says he was going the speed limit, (although the jury didn't believe a word of it).

THE WORDS (AL)THOUGH.3: When although or though begins an adverb clause that is before the
element it modifies into, use a comma after the adverb clause before the main clause of the sentence.

(Although it was raining), we decided to go to the game anyway.
(Though I don't believe him), he said he was not with her.
(Although she is my sister), I have doubts about her innocence.

THE WORDS (AL)THOUGH.4: When the adverb clause is in the middle of the element it modifies
into, surround the adverb clause with commas.

I intend, (though it is difficult), to be there to help her during this period of time.
He is, (though not everyone he works with believes it), a tyrant at home.
She stayed, (although she didn't want to), for X rays and other tests.

THE WORD THOUGH.5: When it is used as a parenthetical, the word though is surrounded by
punctuation.
He was standing by the car, though.
I saw him there, though, later in the evening.
She, though, has other job possibilities.

THE WORD ET CETERA.1: Use commas to surround et cetera when it follows a list that has internal
commas.
Records, reports, abstracts, et cetera, are needed for the transaction.
Books, papers, et cetera, filled every inch of the room.
There were vans, trucks, and cars, et cetera, on his lot.

THE WORD ET CETERA.2: Use commas to surround et cetera when it follows a list even when the list
itself does not need commas.
Records and reports and abstracts, et cetera, are needed for the transaction.
Books and papers, et cetera, filled every inch of the room.
There were vans and trucks and cars, et cetera, on his lot.

THE WORD ET CETERA.3: Use commas to surround et cetera when it is used after just one word
rather than after a list.
Records, et cetera, are needed for the transaction.
Books, et cetera, filled every inch of the room.
There were cars, et cetera, on his lot.

THE WORD ET CETERA.4: Use commas to surround and so forth, and the like, and and such when
they follow a list that has internal commas.
Records, reports, abstracts, and so forth, are needed for the transaction.
Books, papers, and the like, filled every inch of the room.
There were vans, trucks, cars, and such, on his lot.

THE WORD ET CETERA.5: Do not use commas to surround and so forth, and the like, and and such
when they follow a list that does not have internal commas.

Records and reports and abstracts and so forth are needed for the transaction.
Books and papers and the like filled every inch of the room.
There were vans and trucks and cars and such on his lot.

THE WORD ET CETERA.6: Do not use commas to surround and so forth, and the like, and and such
when they are used after just one word rather than after a list.
Records and so forth are needed for the transaction.
Books and the like filled every inch of the room.
There were cars and such on his lot.

THE WORD HOWEVER.1: Use a semicolon or period in front of and a comma after the word however
when it begins a sentence.
We saw them earlier; however, they did not attend the function.
she said she sent the email on Friday; however, I did not get it.
Hank, Marty, and John helped. However, Mary, my sister, did not get better.

THE WORD HOWEVER.2: Use commas around the word however when it is in the middle of the
sentence and a comma in front of it when it is at the end of the sentence.
I did not see him, however, until later in the week.
My surgeon, however, did not inform me of the complications.
She had several responsibilities in the company, however.

THE WORD HOWEVER.3: Surround a dependent clause that begins with the word however. Put a
comma before the clause at the end and a comma after the clause at the beginning.
I will stay, (however long it might take).
He kept an eye on her, (however engrossed he was in his work), while his dad was out.
(However painful it might be), she decided to speak out about the tragedy.

THE WORD OKAY.1: Spell out the word okay even though you might see it abbreviated OK or O.K. in
other contexts.
I am feeling okay today, sir.
Okay. How far away would you estimate the truck to be?
Okay. Fine. Show me where that is on this diagram.

THE WORD OKAY.2: When okay is at the beginning of a sentence, use a period after it.

Okay. Do you know (when that occurred)?
Okay. Fine. Were you involved in that decision?
All right. Okay. Lets see whether we can nail this down.

THE WORD OKAY.3: If the word okay is followed by direct address, put a comma after okay and a
period after the direct address.
Okay, sir. Put your initials on the diagram at that point.
Okay, Mr. Steward. Please bring those to tomorrow's session.
Okay, Your Honor. I will make a note of that.

THE WORD OKAY.4: When okay is at the end of a sentence, use a period or question mark in front of
it for the statement or question and a period or question mark after it, depending on the intonation of
the speaker.
Your doctor prescribed it February 6. Okay.
You have testified you were alone. Okay.
We will put this with the other papers. Okay?

THE WORD OKAY.5: When okay is in the middle of a sentence and expresses a complete thought, use
a pair of dashes around okay with no terminal punctuation inside the dash.
I was walking with them -- okay -- when the disturbance began.
We sent them to the boss -- okay -- and intended that to be the end of it.
she made the decision to stay -- okay -- despite the dangers.

THE WORD OKAY.6: When okay is in the middle of the sentence and is asking a question, use a pair of
dashes around okay with a question mark after it.
I understand that you were there -- okay? -- and didn't know what to do.
I need you to look at this -- okay? -- and tell me your interpretation of It.
This is the contract signed by our company -- okay? -- and then sent to yours.

THE WORD OKAY.7: When okay is in the middle of a sentence and has little or no meaning, use a pair
of commas around okay as a throwaway.
We were in the alley, okay, when we saw him, okay, come out of the store.
He was standing, okay, near the door.
They had several, okay, that I wanted, okay, but couldn't afford.

THE WORD PLEASE.1: Use no punctuation with the word please when it is at the beginning of a
sentence.
Please hand this to the witness.
Please tell me when you have finished reading these pages.
Please do not answer that question.

THE WORD PLEASE.2: Put a comma in front of the word please when it is at the end of a sentence.

I want to know her first and last name, please.
send me her phone number, please.
Mark this as Exhibit 33, please.

THE WORD PLEASE.3: Use no punctuation with the word please when it is truly in the middle of a
sentence.
Would you please put that with the others.
Will you please tell me your annual salary for the first year.
Can you please put that aside.

THE WORD SIC.1: Use the word sic in brackets after an element where the word or words are blatantly
and/or factually incorrect.
We sent it on Friday, June 31 [Sic].
We traveled that weekend to the capital of Kentucky, Louisville [sic].
The first moon landing in 1979 [sic] Supported our program.

THE WORD SIC.2: Do not use the word sic for a slight mispronunciation or for words that are made
up.
It caused a nuclear disaster. (though he said nucular)
It caused both of us to shudder. (though he said bof)
There was a slight "crink" in my leg muscle.

THE WORD SIC.3: Do not use the word sic when the error is immediately corrected.
A It is spelled V-a-l-l-i-u-m.
MR. NELSON: No. It is V-a-l-i-u-m.
THE WITNESS: Thank you.

Q How long did you live in Illinois? Danville, was it?
A It was Danville, Indiana, not Illinois.

THE WORD SO.1: When so is a subordinate conjunction and means "so that" or "in order that" and
begins a dependent clause that is at the end of the unit it modifies into, use no punctuation before the
clause.
She left at 4:00 (so she could catch the train to New York).
I helped him with the figures (So we could finish the project in time).
We mailed the payment early (So we would get credit before the next billing).

THE WORD SO.2: When so is a subordinate conjunction and means "so that" or "in order that" and
begins a dependent clause that is at the beginning of the unit it modifies into, use a comma after the
clause.
(So she could catch the train to New York), she left at 4:00 to walk to the station.
(So we could finish the project in time), I helped him with the figures.
(So we would get credit before the next billing), we mailed the payment early.

THE WORD SO.3: When so is a subordinate conjunction and means "so that" or "In order that" and
begins a dependent clause, use commas around the clause when it is in the middle of the unit it modifies
into.
She left at 4:00, (So she could catch the train to New York), to walk to the station.
I helped him, (So we could finish the project in time), with the figures.
We mailed, (So we would get credit before the next billing), the payment early.

THE WORD SO.4: When So is a conjunctive adverb and means "therefore," use a period or semicolon
in front of it and no comma after it because it is one syllable.
John, Scott, and Wayne arrived on Friday, September 5. So Marion, Carol, and Cliff had
to handle the orientation as I was out of town.
(Therefore, Marion, Carol, and Cliff had to handle....)
He had drunk too much; so he had no business driving.
(Therefore, he had no business driving. )
The red Buick was moving erratically; so I pulled over and let him go by.
(Therefore, I pulled over and let him go by.)

THE WORD SO.5: When so is the last word before someone trails off, put a semicolon or period in
front of so and a dash or ellipses after it to show the trailing off (whichever you have chosen to use for
trailing off).
We had not been there for weeks; so --
We had not been there for weeks; So...
She was at home on Tuesday, May 7, with her brother, sister, and me. So --
she was at home on Tuesday, May 7, with her brother, sister, and me. So...
The weather prevented us from leaving when we had planned; so --
The weather prevented us from leaving when we had planned; so...

THE WORDS TOO AND ALSO.1: Do not use a comma before too and also when they come at the end
of the sentence.
I went with him into the room too.
She needed another copy of it also.
We had a difficult time accepting that too.

THE WORDS TOO AND ALSO.2: Do not use a comma before too and also when they come in the
middle of the sentence.
He too needed the exam.
The contract also needs to be read.
We were also involved in several other projects.

THE WORDS TOO AND ALSO.3: If too is at the beginning of the sentence, do not use a comma after it;
if also is at the beginning of the sentence, use a comma after it.
Too I don't think he needed to be there.
Also, she was not committed to the same goals.
Also, the company decided to change the rate midstream.

THE WORD WHAT.1: When what is used in a question, put a question mark at the end of the question
without regard to the position of the word what.
What actions were you contemplating?
You were contemplating what actions?

What did you do?
You did what?
What were the consequences?
The consequences were what?

THE WORD WHAT.2: In the idiomatic expression what about... and how about..., put a question mark
at the end of the question even though it is not a complete grammatical sentence and a second question
mark for a question that follows.
What about the company?
What about your brother? Was he involved?
What about the island vacation? Were you able to go?
How about the van?
How about the summer? Did he join you then?
How about your education? Where did you get your degree?

THE WORD WHAT.3: When the word what is being used as a throwaway word, surround it with
commas.
You said there, what, were problems with the purchase order?
He knew the company, what, was going to be bought out?
It was after the 5th that he, what, came to work for you?

THE WORDS YES AND NO.1: For the plural of yes, use yes's; the plural of no, use no's.
You need to use yes's and no's rather than nodding your head.
All we need are yes's and no's.
Did you say to use yes's and no's?

THE WORDS YES AND NO.2: When the word yes or no is used generically and refers to a general
positive or negative response, do not put quotes around it.
This requires a yes-or-no answer.
You don't have to explain. Just give her a yes or no.
All you have to do is give me a general yes or no.

THE WORDS YES AND NO.3: When the word yes or no is used in a specific sense as a possible answer,
use quotes around it and cap it.

You need to say "Yes" or "No" or "I don't know" or "I am not sure."
You have to respond with "Yes," not "Uh-huh."
Please just use "No" when you mean it. Don't shake your head.
A No.
Q I am sorry. Was that "No"?
A "No."

THE WORDS YES AND NO.4: When the word yes or no is said multiple times, use commas or periods
to separate the words.
Q Were you aware of the affair?
A Yes, yes, yes.
A Yes. Yes. Yes.
Q Were the injuries life threatening?
A No, unh-unh.
A No. Unh-unh.

THE WORDS YES AND NO.5: When the words after the yes or no simply reflect or "echo" the words of
the question, use a comma after the yes or no.
Q Did you see her earlier in the day?
A Yes, I did.
A Yes, I saw her.
A No, I didn't.
A No, I did not see her.

THE WORDS YES AND NO.6: When the words after the yes or no do not repeat or echo the words of
the question but provide additional information, use a period after the yes or no.
Q Did you see her earlier in the day?
A Yes. She had left with her sister.
A Yes. I think it was around 10:00.
A No. I had to leave before she arrived.
A No. I had an appointment away from the office.

THE WORDS YES AND NO.7: When the words after the yes or no begin with coordinate conjunctions
like but or subordinate conjunctions like because or though, use a period after the yes or no.

Q Did you see her earlier in the day?
A Yes. And we didn't speak at the time.
A Yes. Because she had something I needed.
A No. But The next day.
A No. Nor anytime later.
Q Was she involved in the deception?
A No. Nor was her sister.
A No. Though I didn't know it at the time.
A Yes. And no one could prove it.
A Yes. But along with her siblings.
Q4 Did they travel together?
A No. Although I think they did meet up later.
No. Or at least not on that trip. A
A Yes. But they were concerned about security.
A Yes. Since it was cheaper.

THE WORDS YES AND NO.8: If the answer continues after the yes or no and its echoed answer -- e.g.,
after "Yes, I did" or "No, she hasn't" -- put a period after the echoed answer before the addition of
another sentence.
Q Have you attended all board meetings?
Yes, I have. I have not missed one. A
Q Did she seem interested in your offer?
A No, she didn't seem interested. She was happy where she was.
Q A
Was she a part of the team that did the analysis?
Yes, she was. Later, however, she resigned from that team.

THE WORDS YES AND NO.9: When the word yes or no is at the end of the sentence, it takes a comma
in front of it.
I saw her that day, yes.
The bank did not have the record of the transaction, no.
The injury was to her left hand, yes.

THE WORDS YES AND NO.10: When the word yes or no is in the middle of the sentence and the
sentence is complete and makes sense without it, surround the word with commas.

She did not write to me, no, when she was away.
I wasn't aware of it at the time but, yes, was shocked to find it out later.
The house was locked, yes, with an alarm system.

## MAKING WORDS PLURAL

PLURALS.1: When a word ends in s, z, x, the "soft" ch, or sh, add -es to make it plural.
fox foxes Mr. Hess the Hesses
wish wishes Mr. Perez the Perezes
pass passes church churches
box boxes gash gashes
beach beaches quiz quizzes
witness witnesses class classes

PLURALS.2: When a word ends in any letter other than s, z, x, the "soft" ch, or sh, add -s to make it
plural.
affidavit affidavits elbow elbows
picture pictures trial trials
lawyer lawyers tripod tripods
mutt mutts machine machines
shoe shoes ClOCK clocks
Stone stones computer computers

PLURALS.3: When making a proper name plural, do not change the spelling of the name.
Mary Marys Bono Bonos
Loney Loneys Wolf Wolfs
Marino Marinos Ray Rays

PLURALS.4: If a word ends in y and a vowel precedes the y, add an -s to make the word plural.

attorney attorneys display displays
alloy alloys delay delays
journey journeys Survey Surveys

PLURALS.5: If a word ends in y and a consonant precedes the y, change the y to i and add -es to make
the word plural.
company companies secretary secretaries
property properties liberty liberties
quality qualities minority minorities

PLURALS.6: If a word that ends in o has to do with music, add only an -s to make it plural.
Soprano sopranos alto altos
cello cellos radio radios
banjo banjos piano pianos

PLURALS.7: If a word ends in o and a consonant precedes the o, generally add -es to make the word
plural.
hero heroes veto vetoes
tomato tomatoes torpedo torpedoes
innuendo innuendoes potato potatoes

PLURALS.8: If a word ends in o and a vowel precedes the o, generally add -s to make the word plural.

Studio studios rodeo rodeos
patio patios embryo embryos
ratio ratios cameo cameos

PLURALS.9: For some words that end in -f, change the f to v and add -es for the plural form.

half halves calf calves
wife wives life lives
scarf Scarves wolf wolves

PLURALS.10: For other words that end in -f and those that end in -fe or -ff, add -s for the plural form.

chef chefs Safe Safes
cuff cuffs reef reefs
plaintiff plaintiffs bailiff bailiffs

PLURALS.11: For some words, use the same form for the plural as for the singular.
sheep sheep fish fish
deer deer moose moose

PLURALS.12: For some words, change the internal vowel to make the word plural.
mouse mice louse lice
man men foot feet

PLURALS.13: For some words, add an -en for the plural form.
OX oxen child children

PLURALS.14: When the singular form of the Latin word ends in -is, use -es for the plural.
basis bases
oasis oases
analysis analyses

PLURALS.15: When the singular form of the Latin word ends in -um, use -a for the plural.
Curriculum curricula
addendum addenda
memorandum memoranda

PLURALS.16: When the singular form of the Latin word ends in -us, use -i for the plural.
alumnus alumni
cactus cacti
nucleus nuclei

PLURALS.17: When the singular form of the Latin word ends in -a, use -ae for the plural.
vertebra vertebrae
bursa bursae
alumna alumnae

PLURALS.18: When the singular form of the Latin word ends in -on, use -a for the plural.

criterion criteria
phenomenon phenomena

PLURALS.19: When the singular form of the Latin word ends in -ex or -ix, use -ices for the plural.

appendix appendices or appendixes
index indices or indexes

PLURALS.20: Make titles in front of names plural according to the way they are said.
SINGULAR PLURAL
Dr. Wilson Drs. Wilson or Dr. Wilsons
Mr. Wilson Messrs. Wilson or Mr. Wilsons
Mrs. Wilson Mmes. Wilson or Mrs. Wilsons
Miss Wilson Misses Wilson
Ms. Wilson Mss. Wilson
Dr. Miller and Dr. Hill Drs. Miller and Hill
Mr. Miller and Mr. Hill Messrs. Miller and Hill
Mrs. Miller and Mrs. Hill Mmes. Miller and Hill
Miss Miller and Miss Hill Misses Miller and Hill
Ms. Miller and Ms. Hill Mss. Miller and HIll

PLURALS.21: If a compound noun is a solid word, follow the appropriate rules, and add the plural to
the end of the word.
roommate roommates bookkeeper bookkeepers
bellhop bellhops cupful cupfuls
reindeer reindeer lineman linemen

PLURALS.22: If a compound noun is hyphenated or multiple words AND it contains a main noun
within it, make the main noun plural according to the appropriate rules.
editor in chief editors in chief
rule of thumb rules of thumb
lady-in-waiting ladies-in-waiting
run batted In runs batted in
attorney general attorneys general
brother-in-law brothers-in-law

PLURALS.23: If a compound noun is hyphenated or multiple words AND it contains NO main noun
within it, add the plural to the end according to the appropriate rules.
go-between go-betweens
look-alike look-alikes
know-it-all know-it-alls

PLURALS.24: Use an apostrophe s or an s alone to make an abbreviation plural.
M.D.'s or M.D.s or MD's or MDs
R.N.'s or R.N.s or RN's or RNs
Ph.D.'s or Ph.D.s or PhD's or PhDs
IOU's or IOUs
SOS's or SOSs
SAT's or SATs

PLURALS.25: Use an apostrophe s or an s alone to make a number plural.
She is in her 60's.
She is in her 60s.
The weather was only in the 40's today.
The weather was only in the 40s today.
She left the firm in the 1990's.
She left the firm in the 1990s.

PLURALS.26: Abbreviate the word number as No. in front of a figure. The plural of the abbreviation
No. is Nos.
That is Exhibit No. 3.
We are looking at Exhibits Nos. 3, 4, and 5.
It is referenced in No. 5
It is referenced in Nos. 5 and 7.
Look at paragraph No. 7.
Look at paragraphs Nos. 7 and 10.

PLURALS.27: Use an apostrophe s or an s alone to make a letter plural.
