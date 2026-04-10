"""
Core Moodle .mbz backup builder.

Generates a complete Moodle backup archive from a list of exam sections,
each containing MC questions and an optional essay question.
"""
import tarfile
import time
from html import escape
from io import BytesIO
from pathlib import Path

GRADE_LETTERS = [
    (90.0, "A"),
    (80.0, "B"),
    (70.0, "C"),
    (60.0, "D"),
    (50.0, "E"),
    (0.0, "F"),
]

EMPTY_XML = '<?xml version="1.0" encoding="UTF-8"?>\n'
EMPTY_INFOREF = EMPTY_XML + '<inforef>\n</inforef>\n'
EMPTY_FILTERS = EMPTY_XML + '<filters>\n</filters>\n'
EMPTY_ROLES = EMPTY_XML + '<roles>\n  <role_overrides>\n  </role_overrides>\n  <role_assignments>\n  </role_assignments>\n</roles>\n'
EMPTY_CALENDAR = EMPTY_XML + '<events>\n</events>\n'
EMPTY_GRADE_HISTORY = EMPTY_XML + '<grade_history>\n  <grade_grades>\n  </grade_grades>\n</grade_history>\n'
EMPTY_GRADES = EMPTY_XML + '<activity_gradebook>\n  <grade_items>\n  </grade_items>\n  <grade_letters>\n  </grade_letters>\n</activity_gradebook>\n'


class MoodleBackupBuilder:
    """Builds a complete Moodle .mbz backup archive.

    sections: list of dicts, each with:
        - name: str (section heading in quiz)
        - mc_questions: list of question dicts (from question pool JSON)
        - essay: dict with "name" and "text" keys, or None
    """

    COURSE_ID = 1
    COURSE_CONTEXT_ID = 100
    QUIZ_MODULE_ID = 10
    QUIZ_ACTIVITY_ID = 10
    LABEL_MODULE_ID = 11
    LABEL_ACTIVITY_ID = 11
    DISCLAIMER_MODULE_ID = 12
    DISCLAIMER_ACTIVITY_ID = 12
    NEWS_FORUM_MODULE_ID = 13
    NEWS_FORUM_ACTIVITY_ID = 13
    QA_FORUM_MODULE_ID = 14
    QA_FORUM_ACTIVITY_ID = 14
    SECTION_ID = 1
    GRADE_CATEGORY_ID = 1
    GRADE_ITEM_QUIZ_ID = 2
    GRADE_ITEM_COURSE_ID = 1
    Q_CAT_TOP = 1

    def __init__(self, *, title, time_open, time_close, timelimit,
                 mc_points, essay_points, sections,
                 contact_name="Edwin", contact_email="edwinsu@dsv.su.se",
                 include_qa_forum=True, now=None):
        self.title = title
        self.time_open = time_open
        self.time_close = time_close
        self.timelimit = timelimit
        self.mc_points = mc_points
        self.essay_points = essay_points
        self.sections = sections
        self.contact_name = contact_name
        self.contact_email = contact_email
        self.include_qa_forum = include_qa_forum
        self.now = now or int(time.time())

        total_mc = sum(len(s["mc_questions"]) for s in sections)
        total_essays = sum(1 for s in sections if s.get("essay"))
        self.total_points = total_mc * mc_points + total_essays * essay_points

    # -- questions.xml -------------------------------------------------------

    def _mc_question_xml(self, q, question_id, cat_id, answer_id_start):
        lines = []
        is_single = q["type"] == "single"
        correct_choices = [c for c in q["choices"] if c["correct"]]
        num_correct = len(correct_choices)
        q_name = escape(f"{q.get('topic', '')} - {q['question'][:60]}")

        lines.append(f'      <question_bank_entry id="{question_id}">')
        lines.append(f'        <questioncategoryid>{cat_id}</questioncategoryid>')
        lines.append(f'        <idnumber>$@NULL@$</idnumber>')
        lines.append(f'        <ownerid>1</ownerid>')
        lines.append(f'        <question_version>')
        lines.append(f'          <question_versions id="{question_id + 5000}">')
        lines.append(f'            <version>1</version>')
        lines.append(f'            <status>ready</status>')
        lines.append(f'            <questions>')
        lines.append(f'              <question id="{question_id + 10000}">')
        lines.append(f'                <parent>0</parent>')
        lines.append(f'                <name>{q_name}</name>')
        lines.append(f'                <questiontext>{escape(q["question"])}</questiontext>')
        lines.append(f'                <questiontextformat>1</questiontextformat>')
        lines.append(f'                <generalfeedback></generalfeedback>')
        lines.append(f'                <generalfeedbackformat>1</generalfeedbackformat>')
        lines.append(f'                <defaultmark>{self.mc_points:.7f}</defaultmark>')
        lines.append(f'                <penalty>0.3333333</penalty>')
        lines.append(f'                <qtype>multichoice</qtype>')
        lines.append(f'                <length>1</length>')
        lines.append(f'                <stamp>exam+{self.now}+q{question_id}</stamp>')
        lines.append(f'                <timecreated>{self.now}</timecreated>')
        lines.append(f'                <timemodified>{self.now}</timemodified>')
        lines.append(f'                <createdby>1</createdby>')
        lines.append(f'                <modifiedby>1</modifiedby>')
        lines.append(f'                <plugin_qtype_multichoice_question>')
        lines.append(f'                  <answers>')

        frac_map = {1: 1.0, 2: 0.5, 3: 0.3333333, 4: 0.25, 5: 0.2}
        pos_frac = frac_map.get(num_correct, 1.0)
        neg_frac = -pos_frac
        aid = answer_id_start
        for c in q["choices"]:
            if is_single:
                frac = 1.0 if c["correct"] else 0.0
            else:
                frac = pos_frac if c["correct"] else neg_frac
            lines.append(f'                    <answer id="{aid}">')
            lines.append(f'                      <answertext>{escape(c["text"])}</answertext>')
            lines.append(f'                      <answerformat>1</answerformat>')
            lines.append(f'                      <fraction>{frac:.7f}</fraction>')
            lines.append(f'                      <feedback></feedback>')
            lines.append(f'                      <feedbackformat>1</feedbackformat>')
            lines.append(f'                    </answer>')
            aid += 1

        lines.append(f'                  </answers>')
        lines.append(f'                  <multichoice id="{question_id + 10000}">')
        lines.append(f'                    <layout>0</layout>')
        lines.append(f'                    <single>{1 if is_single else 0}</single>')
        lines.append(f'                    <shuffleanswers>1</shuffleanswers>')
        lines.append(f'                    <correctfeedback>Correct.</correctfeedback>')
        lines.append(f'                    <correctfeedbackformat>1</correctfeedbackformat>')
        lines.append(f'                    <partiallycorrectfeedback>Partially correct.</partiallycorrectfeedback>')
        lines.append(f'                    <partiallycorrectfeedbackformat>1</partiallycorrectfeedbackformat>')
        lines.append(f'                    <incorrectfeedback>Incorrect.</incorrectfeedback>')
        lines.append(f'                    <incorrectfeedbackformat>1</incorrectfeedbackformat>')
        lines.append(f'                    <answernumbering>abc</answernumbering>')
        lines.append(f'                    <shownumcorrect>1</shownumcorrect>')
        lines.append(f'                    <showstandardinstruction>0</showstandardinstruction>')
        lines.append(f'                  </multichoice>')
        lines.append(f'                </plugin_qtype_multichoice_question>')
        lines.append(f'                <question_hints></question_hints>')
        lines.append(f'                <tags></tags>')
        lines.append(f'              </question>')
        lines.append(f'            </questions>')
        lines.append(f'          </question_versions>')
        lines.append(f'        </question_version>')
        lines.append(f'      </question_bank_entry>')
        return '\n'.join(lines), aid

    def _essay_question_xml(self, name, text, question_id, cat_id, points=None):
        pts = points if points is not None else self.essay_points
        return f"""      <question_bank_entry id="{question_id}">
        <questioncategoryid>{cat_id}</questioncategoryid>
        <idnumber>$@NULL@$</idnumber>
        <ownerid>1</ownerid>
        <question_version>
          <question_versions id="{question_id + 5000}">
            <version>1</version>
            <status>ready</status>
            <questions>
              <question id="{question_id + 10000}">
                <parent>0</parent>
                <name>{escape(name)}</name>
                <questiontext>{escape(text)}</questiontext>
                <questiontextformat>1</questiontextformat>
                <generalfeedback></generalfeedback>
                <generalfeedbackformat>1</generalfeedbackformat>
                <defaultmark>{pts:.7f}</defaultmark>
                <penalty>0.0000000</penalty>
                <qtype>essay</qtype>
                <length>1</length>
                <stamp>exam+{self.now}+q{question_id}</stamp>
                <timecreated>{self.now}</timecreated>
                <timemodified>{self.now}</timemodified>
                <createdby>1</createdby>
                <modifiedby>1</modifiedby>
                <plugin_qtype_essay_question>
                  <essay id="{question_id + 10000}">
                    <responseformat>editor</responseformat>
                    <responserequired>1</responserequired>
                    <responsefieldlines>25</responsefieldlines>
                    <minwordlimit>$@NULL@$</minwordlimit>
                    <maxwordlimit>$@NULL@$</maxwordlimit>
                    <attachments>0</attachments>
                    <attachmentsrequired>0</attachmentsrequired>
                    <graderinfo></graderinfo>
                    <graderinfoformat>1</graderinfoformat>
                    <responsetemplate></responsetemplate>
                    <responsetemplateformat>1</responsetemplateformat>
                    <filetypeslist>$@NULL@$</filetypeslist>
                    <maxbytes>0</maxbytes>
                  </essay>
                </plugin_qtype_essay_question>
                <question_hints></question_hints>
                <tags></tags>
              </question>
            </questions>
          </question_versions>
        </question_version>
      </question_bank_entry>"""

    def _question_category_xml(self, cat_id, name, parent):
        return f"""  <question_category id="{cat_id}">
    <name>{name}</name>
    <contextid>{self.COURSE_CONTEXT_ID}</contextid>
    <contextlevel>50</contextlevel>
    <contextinstanceid>{self.COURSE_ID}</contextinstanceid>
    <info></info>
    <infoformat>0</infoformat>
    <stamp>exam+{self.now}+cat{cat_id}</stamp>
    <parent>{parent}</parent>
    <sortorder>{cat_id}</sortorder>
    <idnumber>$@NULL@$</idnumber>"""

    def _make_questions_xml(self):
        """Build questions.xml. Tracks MC and essay entries separately
        so the quiz can place all essays at the end."""
        lines = ['<?xml version="1.0" encoding="UTF-8"?>', '<question_categories>']

        lines.append(self._question_category_xml(self.Q_CAT_TOP, "top", 0))
        lines.append('    <question_bank_entries>')
        lines.append('    </question_bank_entries>')
        lines.append('  </question_category>')

        qid = 100
        aid = 5000
        self._mc_slots = []   # [(entry_id, mc_points, section_name), ...]
        self._essay_slots = []  # [(entry_id, essay_points, section_name), ...]
        self._q_cat_ids = []

        for sec_idx, section in enumerate(self.sections):
            cat_id = self.Q_CAT_TOP + 1 + sec_idx
            self._q_cat_ids.append(cat_id)
            cat_name = escape(section["name"])

            lines.append(self._question_category_xml(cat_id, cat_name, self.Q_CAT_TOP))
            lines.append('    <question_bank_entries>')

            for q in section["mc_questions"]:
                qid += 1
                xml, aid = self._mc_question_xml(q, qid, cat_id, aid)
                lines.append(xml)
                self._mc_slots.append((qid, self.mc_points, section["name"]))

            essay = section.get("essay")
            if essay:
                qid += 1
                lines.append(self._essay_question_xml(
                    essay["name"], essay["text"], qid, cat_id))
                self._essay_slots.append((qid, self.essay_points, section["name"]))

            lines.append('    </question_bank_entries>')
            lines.append('  </question_category>')

        # Comment box (0-point essay for legal requirement)
        qid += 1
        comment_cat_id = self.Q_CAT_TOP + 1 + len(self.sections)
        self._q_cat_ids.append(comment_cat_id)
        comment_text = (
            "I den här rutan kan ni lämna kommentarer för uppgifter på tentan. "
            "Om ni har en kommentar för någon uppgift, skriv då först uppgiftsnumret "
            "och sedan kommentaren.\n\n"
            "In this box you can leave comments for tasks on the exam. "
            "If you have a comment for a question, write the question number first "
            "and then the comment."
        )
        lines.append(self._question_category_xml(comment_cat_id, "Comments", self.Q_CAT_TOP))
        lines.append('    <question_bank_entries>')
        lines.append(self._essay_question_xml("Kommentarer / Comments", comment_text, qid, comment_cat_id, points=0))
        lines.append('    </question_bank_entries>')
        lines.append('  </question_category>')
        self._comment_slot = (qid, 0.0, "Comments")

        lines.append('</question_categories>')
        return '\n'.join(lines)

    # -- quiz.xml ------------------------------------------------------------

    def _make_quiz_xml(self):
        """Build quiz.xml.

        Layout: all MC first (grouped by section), then all essays at the end.
        MC questions are grouped multiple per page. Essays get their own page each.
        Review is only available after the quiz closes.
        SEB is enabled with client config, no download button.
        """
        MC_PER_PAGE = 5
        # Review bit: 0x10 = AFTER_CLOSE only (nothing during attempt)
        REVIEW_AFTER_CLOSE = 16

        total_mc = len(self._mc_slots)
        total_essays = len(self._essay_slots)

        # Ordered slots: all MC, then all essays
        ordered_slots = list(self._mc_slots) + list(self._essay_slots) + [self._comment_slot]

        lines = [
            '<?xml version="1.0" encoding="UTF-8"?>',
            f'<activity id="{self.QUIZ_ACTIVITY_ID}" moduleid="{self.QUIZ_MODULE_ID}" modulename="quiz" contextid="{self.COURSE_CONTEXT_ID + 10}">',
            f'  <quiz id="{self.QUIZ_ACTIVITY_ID}">',
            f'    <name>{escape(self.title)}</name>',
            f'    <intro>&lt;p&gt;{escape(self.title)}. {total_mc} MC ({self.mc_points:.0f}p each) + {total_essays} essays ({self.essay_points:.0f}p each). Total: {self.total_points:.0f}p.&lt;/p&gt;</intro>',
            f'    <introformat>1</introformat>',
            f'    <timeopen>{self.time_open}</timeopen>',
            f'    <timeclose>{self.time_close}</timeclose>',
            f'    <timelimit>{self.timelimit}</timelimit>',
            f'    <overduehandling>autosubmit</overduehandling>',
            f'    <graceperiod>0</graceperiod>',
            f'    <preferredbehaviour>deferredfeedback</preferredbehaviour>',
            f'    <canredoquestions>0</canredoquestions>',
            f'    <attempts_number>1</attempts_number>',
            f'    <attemptonlast>0</attemptonlast>',
            f'    <grademethod>1</grademethod>',
            f'    <decimalpoints>2</decimalpoints>',
            f'    <questiondecimalpoints>-1</questiondecimalpoints>',
            f'    <reviewattempt>{REVIEW_AFTER_CLOSE}</reviewattempt>',
            f'    <reviewcorrectness>{REVIEW_AFTER_CLOSE}</reviewcorrectness>',
            f'    <reviewmaxmarks>{REVIEW_AFTER_CLOSE}</reviewmaxmarks>',
            f'    <reviewmarks>{REVIEW_AFTER_CLOSE}</reviewmarks>',
            f'    <reviewspecificfeedback>{REVIEW_AFTER_CLOSE}</reviewspecificfeedback>',
            f'    <reviewgeneralfeedback>{REVIEW_AFTER_CLOSE}</reviewgeneralfeedback>',
            f'    <reviewrightanswer>{REVIEW_AFTER_CLOSE}</reviewrightanswer>',
            f'    <reviewoverallfeedback>{REVIEW_AFTER_CLOSE}</reviewoverallfeedback>',
            f'    <questionsperpage>0</questionsperpage>',
            f'    <navmethod>free</navmethod>',
            f'    <shuffleanswers>1</shuffleanswers>',
            f'    <sumgrades>{self.total_points:.5f}</sumgrades>',
            f'    <grade>{self.total_points:.5f}</grade>',
            f'    <timecreated>{self.now}</timecreated>',
            f'    <timemodified>{self.now}</timemodified>',
            f'    <password></password>',
            f'    <subnet></subnet>',
            f'    <browsersecurity>-</browsersecurity>',
            f'    <delay1>0</delay1>',
            f'    <delay2>0</delay2>',
            f'    <showuserpicture>0</showuserpicture>',
            f'    <showblocks>0</showblocks>',
            f'    <completionattemptsexhausted>0</completionattemptsexhausted>',
            f'    <completionminattempts>0</completionminattempts>',
            f'    <allowofflineattempts>0</allowofflineattempts>',
            # SEB: Use SEB client config, no download button
            f'    <subplugin_quizaccess_seb_quiz>',
            f'      <quizaccess_seb_quizsettings>',
            f'        <quizid>{self.QUIZ_ACTIVITY_ID}</quizid>',
            f'        <cmid>{self.QUIZ_MODULE_ID}</cmid>',
            f'        <templateid>0</templateid>',
            f'        <requiresafeexambrowser>4</requiresafeexambrowser>',
            f'        <showsebtaskbar>$@NULL@$</showsebtaskbar>',
            f'        <showwificontrol>$@NULL@$</showwificontrol>',
            f'        <showreloadbutton>$@NULL@$</showreloadbutton>',
            f'        <showtime>$@NULL@$</showtime>',
            f'        <showkeyboardlayout>$@NULL@$</showkeyboardlayout>',
            f'        <allowuserquitseb>$@NULL@$</allowuserquitseb>',
            f'        <quitpassword>$@NULL@$</quitpassword>',
            f'        <linkquitseb>$@NULL@$</linkquitseb>',
            f'        <userconfirmquit>$@NULL@$</userconfirmquit>',
            f'        <enableaudiocontrol>$@NULL@$</enableaudiocontrol>',
            f'        <muteonstartup>$@NULL@$</muteonstartup>',
            f'        <allowcapturecamera>$@NULL@$</allowcapturecamera>',
            f'        <allowcapturemicrophone>$@NULL@$</allowcapturemicrophone>',
            f'        <allowspellchecking>$@NULL@$</allowspellchecking>',
            f'        <allowreloadinexam>$@NULL@$</allowreloadinexam>',
            f'        <activateurlfiltering>$@NULL@$</activateurlfiltering>',
            f'        <filterembeddedcontent>$@NULL@$</filterembeddedcontent>',
            f'        <expressionsallowed>$@NULL@$</expressionsallowed>',
            f'        <regexallowed>$@NULL@$</regexallowed>',
            f'        <expressionsblocked>$@NULL@$</expressionsblocked>',
            f'        <regexblocked>$@NULL@$</regexblocked>',
            f'        <showsebdownloadlink>0</showsebdownloadlink>',
            f'        <allowedbrowserexamkeys></allowedbrowserexamkeys>',
            f'        <timecreated>{self.now}</timecreated>',
            f'      </quizaccess_seb_quizsettings>',
            f'    </subplugin_quizaccess_seb_quiz>',
            f'    <quiz_grade_items>',
            f'    </quiz_grade_items>',
            f'    <question_instances>',
        ]

        # Assign pages: MC grouped MC_PER_PAGE per page, essays 1 per page
        page = 0
        mc_on_current_page = 0
        for slot_idx, (entry_id, maxmark, _sec_name) in enumerate(ordered_slots):
            slot = slot_idx + 1
            is_mc = maxmark == self.mc_points

            if not is_mc:
                page += 1
                mc_on_current_page = 0
            elif mc_on_current_page >= MC_PER_PAGE or mc_on_current_page == 0:
                page += 1
                mc_on_current_page = 1
            else:
                mc_on_current_page += 1

            lines.append(f'      <question_instance id="{1000 + slot}">')
            lines.append(f'        <quizid>{self.QUIZ_ACTIVITY_ID}</quizid>')
            lines.append(f'        <slot>{slot}</slot>')
            lines.append(f'        <page>{page}</page>')
            lines.append(f'        <displaynumber>$@NULL@$</displaynumber>')
            lines.append(f'        <requireprevious>0</requireprevious>')
            lines.append(f'        <maxmark>{maxmark:.7f}</maxmark>')
            lines.append(f'        <quizgradeitemid>$@NULL@$</quizgradeitemid>')
            lines.append(f'        <question_reference id="{2000 + slot}">')
            lines.append(f'          <usingcontextid>{self.COURSE_CONTEXT_ID + 10}</usingcontextid>')
            lines.append(f'          <component>mod_quiz</component>')
            lines.append(f'          <questionarea>slot</questionarea>')
            lines.append(f'          <questionbankentryid>{entry_id}</questionbankentryid>')
            lines.append(f'          <version>$@NULL@$</version>')
            lines.append(f'        </question_reference>')
            lines.append(f'      </question_instance>')

        lines.append(f'    </question_instances>')

        # Quiz section headings: one per section's MC, then one "Essays" section
        lines.append(f'    <sections>')
        sec_id = 0
        slot_cursor = 1

        # Group MC by section name (preserving order)
        seen_sections = []
        section_mc_counts = {}
        for _, _, sec_name in self._mc_slots:
            if sec_name not in section_mc_counts:
                seen_sections.append(sec_name)
                section_mc_counts[sec_name] = 0
            section_mc_counts[sec_name] += 1

        for sec_name in seen_sections:
            sec_id += 1
            lines.append(f'      <section id="{sec_id}"><firstslot>{slot_cursor}</firstslot>'
                         f'<heading>{escape(sec_name)}</heading>'
                         f'<shufflequestions>0</shufflequestions></section>')
            slot_cursor += section_mc_counts[sec_name]

        if self._essay_slots:
            sec_id += 1
            lines.append(f'      <section id="{sec_id}"><firstslot>{slot_cursor}</firstslot>'
                         f'<heading>Essay Questions</heading>'
                         f'<shufflequestions>0</shufflequestions></section>')
            slot_cursor += len(self._essay_slots)

        # Comment box section
        sec_id += 1
        lines.append(f'      <section id="{sec_id}"><firstslot>{slot_cursor}</firstslot>'
                     f'<heading>Kommentarer / Comments</heading>'
                     f'<shufflequestions>0</shufflequestions></section>')

        lines.append(f'    </sections>')

        # Grade feedback boundaries
        lines.append(f'    <feedbacks>')
        boundaries = [
            (90.0, 100.01, "Preliminary grade: A"),
            (80.0, 90.0, "Preliminary grade: B"),
            (70.0, 80.0, "Preliminary grade: C"),
            (60.0, 70.0, "Preliminary grade: D"),
            (50.0, 60.0, "Preliminary grade: E"),
            (0.0, 50.0, "Preliminary grade: F"),
        ]
        for fid, (lo, hi, text) in enumerate(boundaries, 1):
            lines.append(f'      <feedback id="{fid}">')
            lines.append(f'        <feedbacktext>{escape(text)}</feedbacktext>')
            lines.append(f'        <feedbacktextformat>1</feedbacktextformat>')
            lines.append(f'        <mingrade>{self.total_points * lo / 100:.5f}</mingrade>')
            lines.append(f'        <maxgrade>{self.total_points * hi / 100:.5f}</maxgrade>')
            lines.append(f'      </feedback>')
        lines.append(f'    </feedbacks>')

        lines.append(f'    <overrides></overrides>')
        lines.append(f'    <grades></grades>')
        lines.append(f'    <attempts></attempts>')
        lines.append(f'  </quiz>')
        lines.append(f'</activity>')
        return '\n'.join(lines)

    # -- labels --------------------------------------------------------------

    def _make_label_xml(self):
        total_mc = sum(len(s["mc_questions"]) for s in self.sections)
        total_essays = sum(1 for s in self.sections if s.get("essay"))
        total_mc_pts = total_mc * self.mc_points

        # Build section breakdown
        breakdown = ""
        for section in self.sections:
            mc_count = len(section["mc_questions"])
            breakdown += f"&lt;li&gt;{mc_count} multiple choice on {escape(section['name'])} ({self.mc_points:.0f}p each)&lt;/li&gt;"
            if section.get("essay"):
                breakdown += f"&lt;li&gt;1 essay on {escape(section['name'])} ({self.essay_points:.0f}p)&lt;/li&gt;"

        # Grade table
        grade_rows = ""
        for pct, letter in GRADE_LETTERS:
            if pct > 0:
                pts = self.total_points * pct / 100
                grade_rows += f"&lt;br&gt;{letter} – {pts:.0f} poäng / points,"
        grade_rows = grade_rows.rstrip(",")

        info = (
            f"&lt;h1&gt;Information om tentan / Exam information&lt;/h1&gt;"

            f"&lt;h3&gt;Hjälpmedel / Permitted aids&lt;/h3&gt;"
            f"&lt;p&gt;Under tentamen är inga hjälpmedel tillåtna och man får inte besöka andra webbsidor "
            f"än den iLearn-kurs som finns uppsatt för tentamen. Inga andra program får användas, och "
            f"ingen kommunikation med andra får förekomma, med undantag för lärare och tentavakt.&lt;/p&gt;"
            f"&lt;p&gt;&lt;em&gt;No aids are permitted during the exam. You may not visit any websites other than "
            f"the iLearn course set up for the exam. No other programs may be used, and no communication "
            f"with others is allowed, except with teachers and exam invigilators.&lt;/em&gt;&lt;/p&gt;"

            f"&lt;p&gt;Information från kursansvarig under tentamen ges i forumet "
            f"&amp;quot;Information från kursledningen&amp;quot;."
        )
        if self.include_qa_forum:
            info += (
                f"&lt;br&gt;"
                f"Det finns även en möjlighet att skriva frågor till kursledningen i forumet "
                f"&amp;quot;Frågor till lärarna under tentamen&amp;quot;."
            )
        info += (
            f"&lt;/p&gt;"
            f"&lt;p&gt;&lt;em&gt;Information from the course coordinator during the exam is provided in the forum "
            f"&amp;quot;Information från kursledningen&amp;quot;."
        )
        if self.include_qa_forum:
            info += (
                f"&lt;br&gt;"
                f"You can also ask questions to the teachers in the forum "
                f"&amp;quot;Frågor till lärarna under tentamen&amp;quot;."
            )
        info += (
            f"&lt;/em&gt;&lt;/p&gt;"

            f"&lt;h3&gt;Poängfördelning / Point distribution&lt;/h3&gt;"
            f"&lt;p&gt;This exam contains:&lt;/p&gt;&lt;ul&gt;{breakdown}&lt;/ul&gt;"
            f"&lt;p&gt;&lt;strong&gt;Total: {self.total_points:.0f} points&lt;/strong&gt;&lt;/p&gt;"
            f"&lt;p&gt;Delvis rätt svar ger delpoäng. Poängen på en fråga kan aldrig bli lägre än 0.&lt;/p&gt;"
            f"&lt;p&gt;&lt;em&gt;Partially correct answers give partial credit. "
            f"A question score can never go below 0.&lt;/em&gt;&lt;/p&gt;"

            f"&lt;h3&gt;Betygskriterier / Grading criteria&lt;/h3&gt;"
            f"&lt;p&gt;Maxpoäng / Maximum points: {self.total_points:.0f}&lt;/p&gt;"
            f"&lt;p&gt;Minimipoäng för de olika betygen / Minimum points for each grade:"
            f"{grade_rows}&lt;/p&gt;"
            f"&lt;p&gt;&lt;strong&gt;Totalt kan {total_mc_pts:.0f}p erhållas på flervalsfrågorna. "
            f"För betyg högre än D ({self.total_points * 0.6:.0f}p) krävs poäng på båda essäfrågorna.&lt;/strong&gt;&lt;/p&gt;"
            f"&lt;p&gt;&lt;strong&gt;&lt;em&gt;A total of {total_mc_pts:.0f}p can be earned from multiple choice questions. "
            f"To achieve a grade higher than D ({self.total_points * 0.6:.0f}p), "
            f"points on both essay questions are required.&lt;/em&gt;&lt;/strong&gt;&lt;/p&gt;"
        )

        # Section minimum requirements
        sections_with_min = [s for s in self.sections if s.get("min_points")]
        if sections_with_min:
            info += "&lt;h3&gt;Minimikrav per del / Minimum requirements per section&lt;/h3&gt;"
            info += (
                "&lt;p&gt;För godkänt betyg krävs dessutom minst följande poäng per del:&lt;/p&gt;"
                "&lt;ul&gt;"
            )
            for s in sections_with_min:
                info += f"&lt;li&gt;{escape(s['name'])}: minst {s['min_points']}p&lt;/li&gt;"
            info += "&lt;/ul&gt;"
            info += (
                "&lt;p&gt;&lt;em&gt;A passing grade additionally requires at least the following points per section:&lt;/em&gt;&lt;/p&gt;"
                "&lt;ul&gt;"
            )
            for s in sections_with_min:
                info += f"&lt;li&gt;&lt;em&gt;{escape(s['name'])}: at least {s['min_points']}p&lt;/em&gt;&lt;/li&gt;"
            info += "&lt;/ul&gt;"

        info += (
            f"&lt;h3&gt;Automatisk rättning / Automatic grading&lt;/h3&gt;"
            f"&lt;p&gt;Flervalsfrågor rättas automatiskt. Den automatiska rättningen kommer att "
            f"kontrolleras och korrigeras manuellt av lärarna. Essäfrågor rättas manuellt.&lt;/p&gt;"
            f"&lt;p&gt;&lt;em&gt;Multiple choice questions are graded automatically. The automatic grading "
            f"will be reviewed and corrected manually by the teachers. Essay questions are graded "
            f"manually.&lt;/em&gt;&lt;/p&gt;"
        )

        return f"""<?xml version="1.0" encoding="UTF-8"?>
<activity id="{self.LABEL_ACTIVITY_ID}" moduleid="{self.LABEL_MODULE_ID}" modulename="label" contextid="{self.COURSE_CONTEXT_ID + 20}">
  <label id="{self.LABEL_ACTIVITY_ID}">
    <name>Information om tentan</name>
    <intro>{info}</intro>
    <introformat>1</introformat>
    <timemodified>{self.now}</timemodified>
  </label>
</activity>
"""

    def _make_disclaimer_xml(self):
        disclaimer = (
            f"&lt;p&gt;&lt;strong&gt;DO NOT EDIT THIS PAGE MANUALLY&lt;/strong&gt;&lt;/p&gt;"
            f"&lt;p&gt;This page is generated by a script. "
            f"Please email &lt;a href=&quot;mailto:{escape(self.contact_email)}&quot;&gt;"
            f"{escape(self.contact_email)}&lt;/a&gt; for any specific content you want included.&lt;/p&gt;"
            f"&lt;p&gt;/ {escape(self.contact_name)}&lt;/p&gt;"
        )
        return f"""<?xml version="1.0" encoding="UTF-8"?>
<activity id="{self.DISCLAIMER_ACTIVITY_ID}" moduleid="{self.DISCLAIMER_MODULE_ID}" modulename="label" contextid="{self.COURSE_CONTEXT_ID + 30}">
  <label id="{self.DISCLAIMER_ACTIVITY_ID}">
    <name>DO NOT EDIT - Generated page</name>
    <intro>{disclaimer}</intro>
    <introformat>1</introformat>
    <timemodified>{self.now}</timemodified>
  </label>
</activity>
"""

    # -- forums --------------------------------------------------------------

    def _make_news_forum_xml(self):
        """Announcements forum — 'Information från kursledningen'."""
        return f"""<?xml version="1.0" encoding="UTF-8"?>
<activity id="{self.NEWS_FORUM_ACTIVITY_ID}" moduleid="{self.NEWS_FORUM_MODULE_ID}" modulename="forum" contextid="{self.COURSE_CONTEXT_ID + 40}">
  <forum id="{self.NEWS_FORUM_ACTIVITY_ID}">
    <type>news</type>
    <name>Information från kursledningen</name>
    <intro>General news and announcements</intro>
    <introformat>1</introformat>
    <duedate>0</duedate>
    <cutoffdate>0</cutoffdate>
    <assessed>0</assessed>
    <assesstimestart>0</assesstimestart>
    <assesstimefinish>0</assesstimefinish>
    <scale>0</scale>
    <maxbytes>0</maxbytes>
    <maxattachments>1</maxattachments>
    <forcesubscribe>1</forcesubscribe>
    <trackingtype>1</trackingtype>
    <rsstype>0</rsstype>
    <rssarticles>0</rssarticles>
    <timemodified>{self.now}</timemodified>
    <warnafter>0</warnafter>
    <blockafter>0</blockafter>
    <blockperiod>0</blockperiod>
    <completiondiscussions>0</completiondiscussions>
    <completionreplies>0</completionreplies>
    <completionposts>0</completionposts>
    <displaywordcount>0</displaywordcount>
    <lockdiscussionafter>0</lockdiscussionafter>
    <grade_forum>0</grade_forum>
    <discussions></discussions>
    <subscriptions></subscriptions>
    <digests></digests>
    <readposts></readposts>
    <trackedprefs></trackedprefs>
    <poststags></poststags>
    <grades></grades>
  </forum>
</activity>
"""

    def _make_qa_forum_xml(self):
        """Student questions forum — 'Frågor till lärarna under tentamen'."""
        return f"""<?xml version="1.0" encoding="UTF-8"?>
<activity id="{self.QA_FORUM_ACTIVITY_ID}" moduleid="{self.QA_FORUM_MODULE_ID}" modulename="forum" contextid="{self.COURSE_CONTEXT_ID + 50}">
  <forum id="{self.QA_FORUM_ACTIVITY_ID}">
    <type>general</type>
    <name>Frågor till lärarna under tentamen</name>
    <intro>&lt;p&gt;Här kan ni ställa frågor om tentan till lärarna.&lt;/p&gt;
&lt;p&gt;&lt;strong&gt;!OBS! Frågorna ni ställer får inte innehålla någon del av ett svar/lösning till någon fråga på tentan! !OBS!&lt;/strong&gt;&lt;/p&gt;
&lt;p&gt;&lt;em&gt;Here you can ask the teachers questions about the exam.&lt;/em&gt;&lt;/p&gt;
&lt;p&gt;&lt;strong&gt;&lt;em&gt;NOTE! Your questions must not contain any part of an answer/solution to any question on the exam! NOTE!&lt;/em&gt;&lt;/strong&gt;&lt;/p&gt;</intro>
    <introformat>1</introformat>
    <duedate>0</duedate>
    <cutoffdate>0</cutoffdate>
    <assessed>0</assessed>
    <assesstimestart>0</assesstimestart>
    <assesstimefinish>0</assesstimefinish>
    <scale>100</scale>
    <maxbytes>512000</maxbytes>
    <maxattachments>9</maxattachments>
    <forcesubscribe>0</forcesubscribe>
    <trackingtype>1</trackingtype>
    <rsstype>0</rsstype>
    <rssarticles>0</rssarticles>
    <timemodified>{self.now}</timemodified>
    <warnafter>0</warnafter>
    <blockafter>0</blockafter>
    <blockperiod>0</blockperiod>
    <completiondiscussions>0</completiondiscussions>
    <completionreplies>0</completionreplies>
    <completionposts>0</completionposts>
    <displaywordcount>0</displaywordcount>
    <lockdiscussionafter>0</lockdiscussionafter>
    <grade_forum>0</grade_forum>
    <discussions></discussions>
    <subscriptions></subscriptions>
    <digests></digests>
    <readposts></readposts>
    <trackedprefs></trackedprefs>
    <poststags></poststags>
    <grades></grades>
  </forum>
</activity>
"""

    # -- supporting XML ------------------------------------------------------

    def _module_xml(self, module_id, module_name, visible=True):
        v = 1 if visible else 0
        return f"""<?xml version="1.0" encoding="UTF-8"?>
<module id="{module_id}" version="2024100700">
  <modulename>{module_name}</modulename>
  <sectionid>{self.SECTION_ID}</sectionid>
  <sectionnumber>0</sectionnumber>
  <idnumber></idnumber>
  <added>{self.now}</added>
  <score>0</score>
  <indent>0</indent>
  <visible>{v}</visible>
  <visibleoncoursepage>1</visibleoncoursepage>
  <visibleold>{v}</visibleold>
  <groupmode>0</groupmode>
  <groupingid>0</groupingid>
  <completion>0</completion>
  <completiongradeitemnumber>$@NULL@$</completiongradeitemnumber>
  <completionpassgrade>0</completionpassgrade>
  <completionview>0</completionview>
  <completionexpected>0</completionexpected>
  <availability>$@NULL@$</availability>
  <showdescription>0</showdescription>
  <downloadcontent>1</downloadcontent>
  <lang></lang>
  <tags></tags>
</module>
"""

    def _quiz_grades_xml(self):
        return f"""<?xml version="1.0" encoding="UTF-8"?>
<activity_gradebook>
  <grade_items>
    <grade_item id="{self.GRADE_ITEM_QUIZ_ID}">
      <categoryid>{self.GRADE_CATEGORY_ID}</categoryid>
      <itemname>{escape(self.title)}</itemname>
      <itemtype>mod</itemtype>
      <itemmodule>quiz</itemmodule>
      <iteminstance>{self.QUIZ_ACTIVITY_ID}</iteminstance>
      <itemnumber>0</itemnumber>
      <iteminfo>$@NULL@$</iteminfo>
      <idnumber></idnumber>
      <calculation>$@NULL@$</calculation>
      <gradetype>1</gradetype>
      <grademax>{self.total_points:.5f}</grademax>
      <grademin>0.00000</grademin>
      <scaleid>$@NULL@$</scaleid>
      <outcomeid>$@NULL@$</outcomeid>
      <gradepass>{self.total_points * 0.5:.5f}</gradepass>
      <multfactor>1.00000</multfactor>
      <plusfactor>0.00000</plusfactor>
      <aggregationcoef>0.00000</aggregationcoef>
      <aggregationcoef2>0.00000</aggregationcoef2>
      <weightoverride>0</weightoverride>
      <sortorder>2</sortorder>
      <display>0</display>
      <decimals>$@NULL@$</decimals>
      <hidden>0</hidden>
      <locked>0</locked>
      <locktime>0</locktime>
      <needsupdate>0</needsupdate>
      <timecreated>{self.now}</timecreated>
      <timemodified>{self.now}</timemodified>
      <grade_grades></grade_grades>
    </grade_item>
  </grade_items>
  <grade_letters></grade_letters>
</activity_gradebook>
"""

    def _quiz_inforef_xml(self):
        lines = ['<?xml version="1.0" encoding="UTF-8"?>', '<inforef>']
        lines.append('  <grade_itemref>')
        lines.append(f'    <grade_item><id>{self.GRADE_ITEM_QUIZ_ID}</id></grade_item>')
        lines.append('  </grade_itemref>')
        lines.append('  <question_categoryref>')
        lines.append(f'    <question_category><id>{self.Q_CAT_TOP}</id></question_category>')
        for cid in self._q_cat_ids:
            lines.append(f'    <question_category><id>{cid}</id></question_category>')
        lines.append('  </question_categoryref>')
        lines.append('</inforef>')
        return '\n'.join(lines)

    def _section_xml(self):
        seq = [self.DISCLAIMER_MODULE_ID, self.LABEL_MODULE_ID, self.NEWS_FORUM_MODULE_ID]
        if self.include_qa_forum:
            seq.append(self.QA_FORUM_MODULE_ID)
        seq.append(self.QUIZ_MODULE_ID)
        seq_str = ",".join(str(s) for s in seq)
        return f"""<?xml version="1.0" encoding="UTF-8"?>
<section id="{self.SECTION_ID}">
  <number>0</number>
  <name>{escape(self.title)}</name>
  <summary></summary>
  <summaryformat>1</summaryformat>
  <sequence>{seq_str}</sequence>
  <visible>1</visible>
  <availabilityjson>$@NULL@$</availabilityjson>
  <timemodified>{self.now}</timemodified>
</section>
"""

    def _course_xml(self):
        return f"""<?xml version="1.0" encoding="UTF-8"?>
<course id="{self.COURSE_ID}" contextid="{self.COURSE_CONTEXT_ID}">
  <shortname>{escape(self.title)}</shortname>
  <fullname>{escape(self.title)}</fullname>
  <idnumber></idnumber>
  <summary>{escape(self.title)}</summary>
  <summaryformat>1</summaryformat>
  <format>topics</format>
  <showgrades>1</showgrades>
  <newsitems>0</newsitems>
  <startdate>{self.time_open}</startdate>
  <enddate>{self.time_close}</enddate>
  <marker>0</marker>
  <maxbytes>0</maxbytes>
  <legacyfiles>0</legacyfiles>
  <showreports>0</showreports>
  <visible>1</visible>
  <groupmode>0</groupmode>
  <groupmodeforce>0</groupmodeforce>
  <defaultgroupingid>0</defaultgroupingid>
  <lang></lang>
  <theme></theme>
  <timecreated>{self.now}</timecreated>
  <timemodified>{self.now}</timemodified>
  <requested>0</requested>
  <showactivitydates>0</showactivitydates>
  <showcompletionconditions>$@NULL@$</showcompletionconditions>
  <pdfexportfont>$@NULL@$</pdfexportfont>
  <enablecompletion>0</enablecompletion>
  <completionnotify>0</completionnotify>
  <category id="1">
    <name>Miscellaneous</name>
    <description></description>
  </category>
  <tags></tags>
  <customfields></customfields>
  <courseformatoptions>
    <courseformatoption>
      <format>topics</format>
      <sectionid>0</sectionid>
      <name>coursedisplay</name>
      <value>0</value>
    </courseformatoption>
    <courseformatoption>
      <format>topics</format>
      <sectionid>0</sectionid>
      <name>hiddensections</name>
      <value>0</value>
    </courseformatoption>
  </courseformatoptions>
</course>
"""

    def _gradebook_xml(self):
        lines = [
            '<?xml version="1.0" encoding="UTF-8"?>',
            '<gradebook>',
            '  <attributes></attributes>',
            '  <grade_categories>',
            f'    <grade_category id="{self.GRADE_CATEGORY_ID}">',
            f'      <parent>$@NULL@$</parent>',
            f'      <depth>1</depth>',
            f'      <path>/{self.GRADE_CATEGORY_ID}/</path>',
            f'      <fullname>?</fullname>',
            f'      <aggregation>11</aggregation>',
            f'      <keephigh>0</keephigh>',
            f'      <droplow>0</droplow>',
            f'      <aggregateonlygraded>1</aggregateonlygraded>',
            f'      <aggregateoutcomes>0</aggregateoutcomes>',
            f'      <timecreated>{self.now}</timecreated>',
            f'      <timemodified>{self.now}</timemodified>',
            f'      <hidden>0</hidden>',
            f'    </grade_category>',
            '  </grade_categories>',
            '  <grade_items>',
            f'    <grade_item id="{self.GRADE_ITEM_COURSE_ID}">',
            f'      <categoryid>$@NULL@$</categoryid>',
            f'      <itemname>$@NULL@$</itemname>',
            f'      <itemtype>course</itemtype>',
            f'      <itemmodule>$@NULL@$</itemmodule>',
            f'      <iteminstance>{self.GRADE_CATEGORY_ID}</iteminstance>',
            f'      <itemnumber>$@NULL@$</itemnumber>',
            f'      <iteminfo>$@NULL@$</iteminfo>',
            f'      <idnumber>$@NULL@$</idnumber>',
            f'      <calculation>$@NULL@$</calculation>',
            f'      <gradetype>1</gradetype>',
            f'      <grademax>{self.total_points:.5f}</grademax>',
            f'      <grademin>0.00000</grademin>',
            f'      <scaleid>$@NULL@$</scaleid>',
            f'      <outcomeid>$@NULL@$</outcomeid>',
            f'      <gradepass>{self.total_points * 0.5:.5f}</gradepass>',
            f'      <multfactor>1.00000</multfactor>',
            f'      <plusfactor>0.00000</plusfactor>',
            f'      <aggregationcoef>0.00000</aggregationcoef>',
            f'      <aggregationcoef2>0.00000</aggregationcoef2>',
            f'      <weightoverride>0</weightoverride>',
            f'      <sortorder>1</sortorder>',
            f'      <display>0</display>',
            f'      <decimals>$@NULL@$</decimals>',
            f'      <hidden>0</hidden>',
            f'      <locked>0</locked>',
            f'      <locktime>0</locktime>',
            f'      <needsupdate>0</needsupdate>',
            f'      <timecreated>{self.now}</timecreated>',
            f'      <timemodified>{self.now}</timemodified>',
            f'      <grade_grades></grade_grades>',
            f'    </grade_item>',
            '  </grade_items>',
            '  <grade_letters>',
        ]
        for lid, (boundary, letter) in enumerate(GRADE_LETTERS, 1):
            lines.append(f'    <grade_letter id="{lid}">')
            lines.append(f'      <lowerboundary>{boundary:.5f}</lowerboundary>')
            lines.append(f'      <letter>{letter}</letter>')
            lines.append(f'    </grade_letter>')
        lines.extend([
            '  </grade_letters>',
            '  <grade_settings>',
            '    <grade_setting id="">',
            '      <name>minmaxtouse</name>',
            '      <value>1</value>',
            '    </grade_setting>',
            '  </grade_settings>',
            '</gradebook>',
        ])
        return '\n'.join(lines)

    def _moodle_backup_xml(self, filename):
        def _activity(mid, mname, title, directory):
            return (f'        <activity>\n'
                    f'          <moduleid>{mid}</moduleid>\n'
                    f'          <sectionid>{self.SECTION_ID}</sectionid>\n'
                    f'          <modulename>{mname}</modulename>\n'
                    f'          <title>{title}</title>\n'
                    f'          <directory>{directory}</directory>\n'
                    f'          <insubsection></insubsection>\n'
                    f'        </activity>')

        def _setting(level, name, value, ref_type=None, ref_id=None):
            s = f'      <setting><level>{level}</level>'
            if ref_type:
                s += f'<{ref_type}>{ref_id}</{ref_type}>'
            s += f'<name>{name}</name><value>{value}</value></setting>'
            return s

        activities = [
            _activity(self.DISCLAIMER_MODULE_ID, "label", "DO NOT EDIT - Generated page", f"activities/label_{self.DISCLAIMER_MODULE_ID}"),
            _activity(self.LABEL_MODULE_ID, "label", "Exam Information", f"activities/label_{self.LABEL_MODULE_ID}"),
            _activity(self.NEWS_FORUM_MODULE_ID, "forum", "Information från kursledningen", f"activities/forum_{self.NEWS_FORUM_MODULE_ID}"),
        ]
        if self.include_qa_forum:
            activities.append(_activity(self.QA_FORUM_MODULE_ID, "forum", "Frågor till lärarna under tentamen", f"activities/forum_{self.QA_FORUM_MODULE_ID}"))
        activities.append(_activity(self.QUIZ_MODULE_ID, "quiz", escape(self.title), f"activities/quiz_{self.QUIZ_MODULE_ID}"))

        settings = [
            _setting("root", "filename", escape(filename)),
            _setting("root", "users", "0"),
            _setting("root", "anonymize", "0"),
            _setting("root", "role_assignments", "0"),
            _setting("root", "activities", "1"),
            _setting("root", "blocks", "0"),
            _setting("root", "files", "1"),
            _setting("root", "filters", "1"),
            _setting("root", "comments", "0"),
            _setting("root", "badges", "0"),
            _setting("root", "calendarevents", "0"),
            _setting("root", "userscompletion", "0"),
            _setting("root", "logs", "0"),
            _setting("root", "grade_histories", "0"),
            _setting("root", "questionbank", "1"),
            _setting("root", "groups", "0"),
            _setting("root", "competencies", "0"),
            _setting("root", "customfield", "0"),
            _setting("root", "contentbankcontent", "0"),
            _setting("root", "legacyfiles", "0"),
            _setting("section", f"section_{self.SECTION_ID}_included", "1", "section", f"section_{self.SECTION_ID}"),
            _setting("section", f"section_{self.SECTION_ID}_userinfo", "0", "section", f"section_{self.SECTION_ID}"),
            _setting("activity", f"label_{self.DISCLAIMER_MODULE_ID}_included", "1", "activity", f"label_{self.DISCLAIMER_MODULE_ID}"),
            _setting("activity", f"label_{self.DISCLAIMER_MODULE_ID}_userinfo", "0", "activity", f"label_{self.DISCLAIMER_MODULE_ID}"),
            _setting("activity", f"label_{self.LABEL_MODULE_ID}_included", "1", "activity", f"label_{self.LABEL_MODULE_ID}"),
            _setting("activity", f"label_{self.LABEL_MODULE_ID}_userinfo", "0", "activity", f"label_{self.LABEL_MODULE_ID}"),
            _setting("activity", f"forum_{self.NEWS_FORUM_MODULE_ID}_included", "1", "activity", f"forum_{self.NEWS_FORUM_MODULE_ID}"),
            _setting("activity", f"forum_{self.NEWS_FORUM_MODULE_ID}_userinfo", "0", "activity", f"forum_{self.NEWS_FORUM_MODULE_ID}"),
        ]
        if self.include_qa_forum:
            settings.append(_setting("activity", f"forum_{self.QA_FORUM_MODULE_ID}_included", "1", "activity", f"forum_{self.QA_FORUM_MODULE_ID}"))
            settings.append(_setting("activity", f"forum_{self.QA_FORUM_MODULE_ID}_userinfo", "0", "activity", f"forum_{self.QA_FORUM_MODULE_ID}"))
        settings.append(_setting("activity", f"quiz_{self.QUIZ_MODULE_ID}_included", "1", "activity", f"quiz_{self.QUIZ_MODULE_ID}"))
        settings.append(_setting("activity", f"quiz_{self.QUIZ_MODULE_ID}_userinfo", "0", "activity", f"quiz_{self.QUIZ_MODULE_ID}"))

        activities_xml = '\n'.join(activities)
        settings_xml = '\n'.join(settings)

        return f"""<?xml version="1.0" encoding="UTF-8"?>
<moodle_backup>
  <information>
    <name>{escape(filename)}</name>
    <moodle_version>2024100700</moodle_version>
    <moodle_release>4.5</moodle_release>
    <backup_version>2024100700</backup_version>
    <backup_release>4.5</backup_release>
    <backup_date>{self.now}</backup_date>
    <mnet_remoteusers>0</mnet_remoteusers>
    <include_files>1</include_files>
    <include_file_references_to_external_content>0</include_file_references_to_external_content>
    <original_wwwroot>https://localhost</original_wwwroot>
    <original_site_identifier_hash>generated</original_site_identifier_hash>
    <original_course_id>{self.COURSE_ID}</original_course_id>
    <original_course_format>topics</original_course_format>
    <original_course_fullname>{escape(self.title)}</original_course_fullname>
    <original_course_shortname>{escape(self.title)}</original_course_shortname>
    <original_course_startdate>{self.time_open}</original_course_startdate>
    <original_course_enddate>{self.time_close}</original_course_enddate>
    <original_course_contextid>{self.COURSE_CONTEXT_ID}</original_course_contextid>
    <original_system_contextid>1</original_system_contextid>
    <details>
      <detail backup_id="examgen">
        <type>course</type>
        <format>moodle2</format>
        <interactive>1</interactive>
        <mode>70</mode>
        <execution>2</execution>
        <executiontime>0</executiontime>
      </detail>
    </details>
    <contents>
      <activities>
{activities_xml}
      </activities>
      <sections>
        <section>
          <sectionid>{self.SECTION_ID}</sectionid>
          <title>{escape(self.title)}</title>
          <directory>sections/section_{self.SECTION_ID}</directory>
          <parentcmid></parentcmid>
          <modname></modname>
        </section>
      </sections>
      <course>
        <courseid>{self.COURSE_ID}</courseid>
        <title>{escape(self.title)}</title>
        <directory>course</directory>
      </course>
    </contents>
    <settings>
{settings_xml}
    </settings>
  </information>
</moodle_backup>
"""

    # -- public API ----------------------------------------------------------

    def build(self, output_path):
        """Generate the .mbz file."""
        filename = Path(output_path).name

        questions_xml = self._make_questions_xml()
        quiz_xml = self._make_quiz_xml()
        label_xml = self._make_label_xml()
        disclaimer_xml = self._make_disclaimer_xml()

        def add(tar, path, content):
            data = content.encode('utf-8')
            info = tarfile.TarInfo(name=path)
            info.size = len(data)
            info.mtime = self.now
            tar.addfile(info, BytesIO(data))

        with tarfile.open(output_path, "w:gz") as tar:
            add(tar, "moodle_backup.xml", self._moodle_backup_xml(filename))
            add(tar, "questions.xml", questions_xml)
            add(tar, "gradebook.xml", self._gradebook_xml())
            add(tar, "scales.xml", EMPTY_XML + '<scales_definition>\n</scales_definition>\n')
            add(tar, "roles.xml", EMPTY_XML + '<roles_definition>\n</roles_definition>\n')
            add(tar, "files.xml", EMPTY_XML + '<files>\n</files>\n')
            add(tar, "completion.xml", EMPTY_XML + '<course_completion>\n</course_completion>\n')
            add(tar, "outcomes.xml", EMPTY_XML + '<outcomes_definition>\n</outcomes_definition>\n')
            add(tar, "groups.xml", EMPTY_XML + '<groups>\n  <groupings>\n  </groupings>\n</groups>\n')
            add(tar, "badges.xml", EMPTY_XML + '<badges>\n</badges>\n')
            add(tar, "grade_history.xml", EMPTY_GRADE_HISTORY)

            add(tar, "course/course.xml", self._course_xml())
            add(tar, "course/enrolments.xml", EMPTY_XML + '<enrolments>\n  <enrols>\n  </enrols>\n</enrolments>\n')
            add(tar, "course/roles.xml", EMPTY_ROLES)
            add(tar, "course/filters.xml", EMPTY_FILTERS)
            add(tar, "course/inforef.xml", EMPTY_INFOREF)
            add(tar, "course/calendar.xml", EMPTY_CALENDAR)
            add(tar, "course/completiondefaults.xml", EMPTY_XML + '<course_completion_defaults>\n</course_completion_defaults>\n')
            add(tar, "course/contentbank.xml", EMPTY_XML + '<contents>\n</contents>\n')

            add(tar, f"sections/section_{self.SECTION_ID}/section.xml", self._section_xml())
            add(tar, f"sections/section_{self.SECTION_ID}/inforef.xml", EMPTY_INFOREF)

            # Disclaimer (hidden from students)
            dp = f"activities/label_{self.DISCLAIMER_MODULE_ID}"
            add(tar, f"{dp}/label.xml", disclaimer_xml)
            add(tar, f"{dp}/module.xml", self._module_xml(self.DISCLAIMER_MODULE_ID, "label", visible=False))
            for f_name in ("grades.xml", "inforef.xml", "roles.xml", "filters.xml", "calendar.xml", "grade_history.xml"):
                stub = EMPTY_GRADES if f_name == "grades.xml" else (
                    EMPTY_INFOREF if f_name == "inforef.xml" else (
                    EMPTY_ROLES if f_name == "roles.xml" else (
                    EMPTY_FILTERS if f_name == "filters.xml" else (
                    EMPTY_CALENDAR if f_name == "calendar.xml" else EMPTY_GRADE_HISTORY))))
                add(tar, f"{dp}/{f_name}", stub)

            # Info label
            lp = f"activities/label_{self.LABEL_MODULE_ID}"
            add(tar, f"{lp}/label.xml", label_xml)
            add(tar, f"{lp}/module.xml", self._module_xml(self.LABEL_MODULE_ID, "label"))
            for stub_name, stub in [("grades.xml", EMPTY_GRADES), ("inforef.xml", EMPTY_INFOREF),
                                     ("roles.xml", EMPTY_ROLES), ("filters.xml", EMPTY_FILTERS),
                                     ("calendar.xml", EMPTY_CALENDAR), ("grade_history.xml", EMPTY_GRADE_HISTORY)]:
                add(tar, f"{lp}/{stub_name}", stub)

            # Forums
            EMPTY_GRADING = EMPTY_XML + '<areas>\n</areas>\n'
            forums = [(self.NEWS_FORUM_MODULE_ID, self._make_news_forum_xml())]
            if self.include_qa_forum:
                forums.append((self.QA_FORUM_MODULE_ID, self._make_qa_forum_xml()))
            for mid, forum_xml in forums:
                fp = f"activities/forum_{mid}"
                add(tar, f"{fp}/forum.xml", forum_xml)
                add(tar, f"{fp}/module.xml", self._module_xml(mid, "forum"))
                add(tar, f"{fp}/grades.xml", EMPTY_GRADES)
                add(tar, f"{fp}/grading.xml", EMPTY_GRADING)
                add(tar, f"{fp}/inforef.xml", EMPTY_INFOREF)
                add(tar, f"{fp}/roles.xml", EMPTY_ROLES)
                add(tar, f"{fp}/filters.xml", EMPTY_FILTERS)
                add(tar, f"{fp}/calendar.xml", EMPTY_CALENDAR)
                add(tar, f"{fp}/grade_history.xml", EMPTY_GRADE_HISTORY)

            # Quiz
            qp = f"activities/quiz_{self.QUIZ_MODULE_ID}"
            add(tar, f"{qp}/quiz.xml", quiz_xml)
            add(tar, f"{qp}/module.xml", self._module_xml(self.QUIZ_MODULE_ID, "quiz"))
            add(tar, f"{qp}/grades.xml", self._quiz_grades_xml())
            add(tar, f"{qp}/inforef.xml", self._quiz_inforef_xml())
            add(tar, f"{qp}/roles.xml", EMPTY_ROLES)
            add(tar, f"{qp}/filters.xml", EMPTY_FILTERS)
            add(tar, f"{qp}/calendar.xml", EMPTY_CALENDAR)
            add(tar, f"{qp}/grade_history.xml", EMPTY_GRADE_HISTORY)
