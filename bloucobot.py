# coding=utf-8
"""
bloucobot.py - Sopel Meeting Logger Module
This module is an attempt to implement some of the functionality of Debian's bloucobot
Copyright © 2012, Elad Alfassa, <elad@fedoraproject.org>
Licensed under the Eiffel Forum License 2.

https://sopel.chat
"""
from __future__ import absolute_import, division, print_function, unicode_literals

import codecs
import collections
import os
import re
import time
import hashlib
from string import punctuation, whitespace

from sopel import formatting, module, tools
from sopel.config.types import (FilenameAttribute, StaticSection,
                                ValidatedAttribute)
from sopel.modules.url import find_title

import requests


UNTITLED_MEETING = "Anônimo"


class BloucobotSection(StaticSection):
    """Configuration file section definition"""

    meeting_log_path = FilenameAttribute(
        "meeting_log_path", directory=True, default="~/www/meetings"
    )
    """Path to meeting logs storage directory

    This should be an absolute path, accessible on a webserver."""

    meeting_log_baseurl = ValidatedAttribute(
        "meeting_log_baseurl", default="http://localhost/~sopel/meetings"
    )
    """Base URL for the meeting logs directory"""


def configure(config):
    """
    | name | example | purpose |
    | ---- | ------- | ------- |
    | meeting\\_log\\_path | /home/sopel/www/meetings | Path to meeting logs storage directory (should be an absolute path, accessible on a webserver) |
    | meeting\\_log\\_baseurl | http://example.com/~sopel/meetings | Base URL for the meeting logs directory |
    """
    config.define_section("bloucobot", BloucobotSection)
    config.bloucobot.configure_setting(
        "meeting_log_path", "Enter the directory to store logs in."
    )
    config.bloucobot.configure_setting(
        "meeting_log_baseurl", "Enter the base URL for the meeting logs."
    )


def setup(bot):
    bot.config.define_section("bloucobot", BloucobotSection)


meetings_dict = collections.defaultdict(dict)  # Saves metadata about currently running meetings
"""
meetings_dict is a 2D dict.

Each meeting should have:
channel
time of start
head (can stop the meeting, plus all abilities of puxam)
puxam (can add seligalines to the logs)
title
current missão
ows (what people who aren't voiced want to add)

Using channel as the meeting ID as there can't be more than one meeting in a
channel at the same time.
"""

# To be defined on meeting start as part of sanity checks, used by logging
# functions so we don't have to pass them bot
meeting_log_path = ""
meeting_log_baseurl = ""

# A dict of channels to the vraus that have been created in them. This way
# we can have .listvraus spit them back out later on.
meeting_vraus = {}


# Get the logfile name for the meeting in the requested channel
# Used by all logging functions and web path
def figure_logfile_name(channel):
    if meetings_dict[channel]["title"] == UNTITLED_MEETING:
        name = "untitled"
    else:
        name = meetings_dict[channel]["title"]
    # Real simple sluggifying.
    # May not handle unicode or unprintables well. Close enough.
    for character in punctuation + whitespace:
        name = name.replace(character, "-")
    name = name.strip("-")
    timestring = time.strftime(
        "%Y-%m-%d-%H:%M", time.gmtime(meetings_dict[channel]["start"])
    )
    filename = timestring + "_" + name
    return filename


# Start HTML log
def log_html_start(channel):
    logfile_filename = os.path.join(
        meeting_log_path + channel, figure_logfile_name(channel) + ".html"
    )
    logfile = codecs.open(logfile_filename, "a", encoding="utf-8")
    timestring = time.strftime(
        "%Y-%m-%d %H:%M", time.gmtime(meetings_dict[channel]["start"])
    )
    title = "%s at %s, %s" % (meetings_dict[channel]["title"], channel, timestring)
    logfile.write(
        (
            "<!doctype html><html><head><meta charset='utf-8'>\n"
            "<title>{title}</title>\n</head><body>\n<h1>{title}</h1>\n"
        ).format(title=title)
    )
    logfile.write(
        "<h4>Meeting started by %s</h4><ul>\n" % meetings_dict[channel]["head"]
    )
    logfile.close()


# Write a list item in the HTML log
def log_html_listitem(item, channel):
    logfile_filename = os.path.join(
        meeting_log_path + channel, figure_logfile_name(channel) + ".html"
    )
    logfile = codecs.open(logfile_filename, "a", encoding="utf-8")
    logfile.write("<li>" + item + "</li>\n")
    logfile.close()


# End the HTML log
def log_html_end(channel):
    logfile_filename = os.path.join(
        meeting_log_path + channel, figure_logfile_name(channel) + ".html"
    )
    logfile = codecs.open(logfile_filename, "a", encoding="utf-8")
    current_time = time.strftime("%H:%M:%S", time.gmtime())
    logfile.write("</ul>\n<h4>Meeting ended at %s UTC</h4>\n" % current_time)
    plainlog_url = meeting_log_baseurl + tools.web.quote(
        channel + "/" + figure_logfile_name(channel) + ".txt"
    )
    logfile.write('<a href="%s">Full log</a>' % plainlog_url)
    logfile.write("\n</body>\n</html>\n")
    logfile.close()


# Write a string to the plain text log
def log_plain(item, channel):
    logfile_filename = os.path.join(
        meeting_log_path + channel, figure_logfile_name(channel) + ".txt"
    )
    logfile = codecs.open(logfile_filename, "a", encoding="utf-8")
    current_time = time.strftime("%H:%M:%S", time.gmtime())
    logfile.write("[" + current_time + "] " + item + "\r\n")
    logfile.close()


# Check if a meeting is currently running
def is_meeting_running(channel):
    try:
        return meetings_dict[channel]["running"]
    except KeyError:
        return False


# Check if nick is a chair or head of the meeting
def is_chair(nick, channel):
    try:
        return (
            nick.lower() == meetings_dict[channel]["head"] or
            nick.lower() in meetings_dict[channel]["puxam"]
        )
    except KeyError:
        return False


# Start meeting (also performs all required sanity checks)
@module.commands("vemblouco")
@module.example(".vemblouco", user_help=True)
@module.example(".vemblouco Meeting Title", user_help=True)
@module.require_chanmsg("Meetings can only be started in channels")
def vemblouco(bot, trigger):
    """
    Start a meeting.\
    See [bloucobot module usage]({% link _usage/bloucobot-module.md %})
    """
    if is_meeting_running(trigger.sender):
        bot.say("Já tem um Blouco ativo!")
        return
    # Start the meeting
    meetings_dict[trigger.sender]["start"] = time.time()
    if not trigger.group(2):
        meetings_dict[trigger.sender]["title"] = UNTITLED_MEETING
    else:
        meetings_dict[trigger.sender]["title"] = trigger.group(2)
    meetings_dict[trigger.sender]["head"] = trigger.nick.lower()
    meetings_dict[trigger.sender]["running"] = True
    meetings_dict[trigger.sender]["ows"] = []

    # Set up paths and URLs
    global meeting_log_path
    meeting_log_path = bot.config.bloucobot.meeting_log_path
    if not meeting_log_path.endswith(os.sep):
        meeting_log_path += os.sep

    global meeting_log_baseurl
    meeting_log_baseurl = bot.config.bloucobot.meeting_log_baseurl
    if not meeting_log_baseurl.endswith("/"):
        meeting_log_baseurl = meeting_log_baseurl + "/"

    channel_log_path = meeting_log_path + trigger.sender
    if not os.path.isdir(channel_log_path):
        try:
            os.makedirs(channel_log_path)
        except Exception:  # TODO: Be specific
            bot.say(
                "Blouco não veio: Não consegui criar o diretório de log para este canal"
            )
            meetings_dict[trigger.sender] = collections.defaultdict(dict)
            raise
    # Okay, meeting started!
    log_plain("Blouco trazido pela Porta-estandarte " + trigger.nick.lower(), trigger.sender)
    log_html_start(trigger.sender)
    meeting_vraus[trigger.sender] = []
    bot.say(
        (
            formatting.bold("O Blouco é aqui!") + " mande {0}vrau, {0}blz, "
            "{0}seliga, {0}link, {0}puxam, {0}missão, and {0}ows para "
            "controlar o Blouco. Para partir, mande {0}vaiblouco"
        ).format(bot.config.core.help_prefix)
    )
    bot.say(
        (
            "Quem não está puxando pode participar me enviando uma DM com `{0}ow {1}` seguido de seu comentário."
        ).format(bot.config.core.help_prefix, trigger.sender)
    )


# Change the current missão (will appear as <h3> in the HTML log)
@module.commands("missão")
@module.example(".missão roll call")
def meetingmissão(bot, trigger):
    """
    Change the meeting missão.\
    See [bloucobot module usage]({% link _usage/bloucobot-module.md %})
    """
    if not is_meeting_running(trigger.sender):
        bot.say("Não tem Blouco aqui")
        return
    if not trigger.group(2):
        bot.say("Qual a missão?")
        return
    if not is_chair(trigger.nick, trigger.sender):
        bot.say("Somente Porta-estandarte e Puxadoras podem fazer isso")
        return
    meetings_dict[trigger.sender]["current_missão"] = trigger.group(2)
    logfile_filename = os.path.join(
        meeting_log_path + trigger.sender, figure_logfile_name(trigger.sender) + ".html"
    )
    logfile = codecs.open(logfile_filename, "a", encoding="utf-8")
    logfile.write("</ul><h3>" + trigger.group(2) + "</h3><ul>")
    logfile.close()
    log_plain(
        "Missão atual: {} (trazida por {})".format(trigger.group(2), trigger.nick),
        trigger.sender,
    )
    bot.say(formatting.bold("Missão atual:") + " " + trigger.group(2))


# End the meeting
@module.commands("vaiblouco")
@module.example(".vaiblouco")
def vaiblouco(bot, trigger):
    """
    End a meeting.\
    See [bloucobot module usage]({% link _usage/bloucobot-module.md %})
    """
    if not is_meeting_running(trigger.sender):
        bot.say("Não tem Blouco aqui")
        return
    if not is_chair(trigger.nick, trigger.sender):
        bot.say("Somente Porta-estandarte e Puxadoras podem fazer isso")
        return
    meeting_length = time.time() - meetings_dict[trigger.sender]["start"]
    bot.say(
        formatting.bold("Blouco indo embora!") +
        " Ele ficou %d minutos aqui" % (meeting_length // 60)
    )
    log_html_end(trigger.sender)
    htmllog_url = meeting_log_baseurl + tools.web.quote(
        trigger.sender + "/" + figure_logfile_name(trigger.sender) + ".html"
    )
    fulllog_url = meeting_log_baseurl + tools.web.quote(
        trigger.sender + "/" + figure_logfile_name(trigger.sender) + ".txt"
    )
    log_plain(
        "O Blouco saiu às %s. Tempo aqui: %d minutos"
        % (trigger.nick, meeting_length // 60),
        trigger.sender,
    )
    bot.say("Registro principal: " + htmllog_url)
    bot.say("Registro completo: " + fulllog_url)
    meetings_dict[trigger.sender] = collections.defaultdict(dict)


    r = requests.get(fulllog_url)
    page_source = r.text
    md5 = hashlib.md5(page_source.encode('utf-8')).hexdigest()

    bot.say("Segue o Blouco! " + md5)

    del meeting_vraus[trigger.sender]


# Set meeting puxam (people who can control the meeting)
@module.commands("puxam")
@module.example(".puxam Tyrope Jason elad")
def puxam(bot, trigger):
    """
    Set the meeting puxam.\
    See [bloucobot module usage]({% link _usage/bloucobot-module.md %})
    """
    if not is_meeting_running(trigger.sender):
        bot.say("Não tem Blouco aqui")
        return
    if not trigger.group(2):
        bot.say(
            "Quem vai puxar? Tente `{}puxam Fulana Beltrana_18 C1cl4n4`".format(
                bot.config.core.help_prefix
            )
        )
        return
    if trigger.nick.lower() == meetings_dict[trigger.sender]["head"]:
        meetings_dict[trigger.sender]["puxam"] = trigger.group(2).lower().split(" ")
        puxam_readable = trigger.group(2).lower().replace(" ", ", ")
        log_plain("Puxadoras: " + puxam_readable, trigger.sender)
        log_html_listitem(
            "<span style='font-weight: bold'>Puxadoras:</span> %s"
            % puxam_readable,
            trigger.sender,
        )
        bot.say(formatting.bold("Puxadoras:") + " " + puxam_readable)
    else:
        bot.say("Somente a Porta-estandarte pode consagrar Puxadoras")


# Log vrau item in the HTML log
@module.commands("vrau")
@module.example(".vrau elad will develop a bloucobot")
def meetingvrau(bot, trigger):
    """
    Log an vrau in the meeting log.\
    See [bloucobot module usage]({% link _usage/bloucobot-module.md %})
    """
    if not is_meeting_running(trigger.sender):
        bot.say("Não tem Blouco aqui")
        return
    if not trigger.group(2):
        bot.say(
            "Tente `{}vrau Fulanin vai fazer tal coisa`".format(bot.config.core.help_prefix)
        )
        return
    if not is_chair(trigger.nick, trigger.sender):
        bot.say("Somente a Porta-estandarte e as Puxadoras podem fazer isso")
        return
    log_plain("vrau: " + trigger.group(2), trigger.sender)
    log_html_listitem(
        "<span style='font-weight: bold'>vrau: </span>" + trigger.group(2),
        trigger.sender,
    )
    meeting_vraus[trigger.sender].append(trigger.group(2))
    bot.say(formatting.bold("vrau:") + " " + trigger.group(2))


@module.commands("listvraus")
@module.example(".listvraus")
def listvraus(bot, trigger):
    if not is_meeting_running(trigger.sender):
        bot.say("Não tem Blouco aqui")
        return
    for vrau in meeting_vraus[trigger.sender]:
        bot.say(formatting.bold("vrau:") + " " + vrau)


# Log blz item in the HTML log
@module.commands("blz")
@module.example(".blz vai ser demais isso aí manda ver")
def meetingblz(bot, trigger):
    """
    Log an agreement in the meeting log.\
    See [bloucobot module usage]({% link _usage/bloucobot-module.md %})
    """
    if not is_meeting_running(trigger.sender):
        bot.say("Não tem Blouco aqui")
        return
    if not trigger.group(2):
        bot.say("Tente `{}blz vai ser demais isso aí manda ver`".format(bot.config.core.help_prefix))
        return
    if not is_chair(trigger.nick, trigger.sender):
        bot.say("Somente a Porta-estandarte e as Puxadoras podem fazer isso")
        return
    log_plain("blz: " + trigger.group(2), trigger.sender)
    log_html_listitem(
        "<span style='font-weight: bold'>blz: </span>" + trigger.group(2),
        trigger.sender,
    )
    bot.say(formatting.bold("blz:") + " " + trigger.group(2))


# Log link item in the HTML log
@module.commands("link")
@module.example(".link http://example.com")
def meetinglink(bot, trigger):
    """
    Log a link in the meeing log.\
    See [bloucobot module usage]({% link _usage/bloucobot-module.md %})
    """
    if not is_meeting_running(trigger.sender):
        bot.say("Não tem Blouco aqui")
        return
    if not trigger.group(2):
        bot.say(
            "Tente `{}link https://algum-website.exemplo/`".format(
                bot.config.core.help_prefix
            )
        )
        return
    if not is_chair(trigger.nick, trigger.sender):
        bot.say("Somente a Porta-estandarte e as Puxadoras podem fazer isso")
        return
    link = trigger.group(2)
    if not link.startswith("http"):
        link = "http://" + link
    try:
        title = find_title(link)
    except Exception:  # TODO: Be specific
        title = ""
    log_plain("LINK: %s [%s]" % (link, title), trigger.sender)
    log_html_listitem('<a href="%s">%s</a>' % (link, title), trigger.sender)
    bot.say(formatting.bold("LINK:") + " " + link)


# Log seligarmational item in the HTML log
@module.commands("seliga")
@module.example(".seliga caiu a transmissão")
def meetingseliga(bot, trigger):
    """
    Log an seligarmational item in the meeting log.\
    See [bloucobot module usage]({% link _usage/bloucobot-module.md %})
    """
    if not is_meeting_running(trigger.sender):
        bot.say("Não tem Blouco aqui")
        return
    if not trigger.group(2):
        bot.say(
            "Tente `{}seliga alguma informação relevante`".format(bot.config.core.help_prefix)
        )
        return
    if not is_chair(trigger.nick, trigger.sender):
        bot.say("Somente a Porta-estandarte e as Puxadoras podem fazer isso")
        return
    log_plain("seliga: " + trigger.group(2), trigger.sender)
    log_html_listitem(trigger.group(2), trigger.sender)
    bot.say(formatting.bold("seliga:") + " " + trigger.group(2))



@module.commands("ow")
def take_ow(bot, trigger):
    """
    Log a ow, to be shown with other ows when a chair uses .ows.
    Intended to allow owary from those outside the primary group of people
    in the meeting.

    Used in private message only, as `.ow <#channel> <ow to add>`

    See [bloucobot module usage]({% link _usage/bloucobot-module.md %})
    """
    if not trigger.group(3):  # <2 arguments were given
        bot.say(
            "Uso: {}ow <comentário>".format(
                bot.config.core.help_prefix
            )
        )
        return

    message = trigger.group(2)
    if not is_meeting_running(trigger.sender):
        bot.say("Não tem Blouco aqui.")
    else:
        meetings_dict[trigger.sender]["ows"].append((trigger.nick, message))
        bot.say(
            "Seu Ow foi gravado. Vai aparecer quando as Puxadoras me pedirem para mostrar os Ows."
        )
        bot.say(
            "Ow gravado", meetings_dict[trigger.sender]["head"]
        )


@module.commands("ows")
def show_ows(bot, trigger):
    """
    Show the ows that have been logged for this meeting with .ow.

    See [bloucobot module usage]({% link _usage/bloucobot-module.md %})
    """
    if not is_meeting_running(trigger.sender):
        return
    if not is_chair(trigger.nick, trigger.sender):
        bot.say("Somente Porta-estandarte e Puxadoras podem fazer isso")
        return
    ows = meetings_dict[trigger.sender]["ows"]
    if ows:
        msg = "Lista de Ows:"
        bot.say(msg)
        log_plain("<%s> %s" % (bot.nick, msg), trigger.sender)
        for ow in ows:
            msg = "<%s> %s" % ow
            bot.say(msg)
            log_plain("<%s> %s" % (bot.nick, msg), trigger.sender)
        meetings_dict[trigger.sender]["ows"] = []
    else:
        bot.say("Não tem Ows")

