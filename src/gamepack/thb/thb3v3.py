# -*- coding: utf-8 -*-
from game.autoenv import Game, EventHandler, Action, GameError, GameEnded, PlayerList
from game import TimeLimitExceeded

from actions import *
from itertools import cycle
from collections import defaultdict
import random

from utils import BatchList, check, CheckFailed, classmix

from .common import *

import logging
log = logging.getLogger('THBattle')

game_ehs = set()
def game_eh(cls):
    game_ehs.add(cls)
    return cls

@game_eh
class DeathHandler(EventHandler):
    def handle(self, evt_type, act):
        if evt_type == 'action_after' and isinstance(act, Damage):
            tgt = act.target
            if tgt.life > 0: return act
            g = Game.getgame()
            if not g.process_action(TryRevive(tgt, dmgact=act)):
                g.process_action(PlayerDeath(act.source, tgt))
        return act

class ActFirst(object): # for choose_option
    pass

class Identity(PlayerIdentity):
    class TYPE:
        HIDDEN = 0
        HAKUREI = 1
        MORIYA = 2

class THBattle(Game):
    n_persons = 6

    def game_start(self):
        # game started, init state
        from cards import Card, Deck, CardList

        self.deck = Deck()

        ehclasses = list(action_eventhandlers) + list(game_ehs)

        self.forces = forces = BatchList([PlayerList(), PlayerList()])
        for i, p in enumerate(self.players):
            f = i%2
            p.force = f
            forces[f].append(p)


        # choose girls -->
        from characters import characters as chars

        if Game.SERVER_SIDE:
            choice = [
                CharChoice(cls, cid)
                for cls, cid in zip(random.sample(chars, 18), xrange(18))
            ]
        elif Game.CLIENT_SIDE:
            choice = [
                CharChoice(None, i)
                for i in xrange(18)
            ]
        fchoice = [
            choice[:9],
            choice[9:],
        ]

        '''
        # FOR DBG VER
        #chars = list(reversed(_chars))
        chars = list(_chars)
        if Game.SERVER_SIDE:
            choice = [
                CharChoice(cls, cid)
                for cls, cid in zip(chars[:18], xrange(18))
            ]
        elif Game.CLIENT_SIDE:
            choice = [
                CharChoice(None, i)
                for i in xrange(18)
            ]
        fchoice = [
            choice[:9],
            choice[9:],
        ]'''

        # -----------

        forces[0].reveal(fchoice[0])
        forces[1].reveal(fchoice[1])

        chosen_girls = []
        pl = PlayerList(self.players)
        def process(p, cid):
            try:
                retry = p._retry
            except AttributeError:
                retry = 3

            retry -= 1
            try:
                check(isinstance(cid, int))
                f = p.force
                check(0 <= cid < len(choice))
                c = choice[cid]
                check(c in fchoice[f])
                if c.chosen and retry > 0:
                    p._retry = retry
                    raise ValueError
                c.chosen = p
                chosen_girls.append(c)
                self.emit_event('girl_chosen', c)
                pl.remove(p)
                return c
            except CheckFailed as e:
                try:
                    del p._retry
                except AttributeError:
                    pass
                return None

        self.players.user_input_all('choose_girl', process, choice, timeout=30) # ALL?? NOT ANY?!!

        # now you can have them.
        forces[1].reveal(fchoice[0])
        forces[0].reveal(fchoice[1])

        # if there's any person didn't make a choice -->
        # FIXME: this can choose girl from the other force!
        if pl:
            choice = [c for c in choice if not c.chosen]
            sample = sync_primitive(random.sample(xrange(len(choice)), len(pl)), self.players)
            for p, i in zip(pl, sample):
                c = choice[i]
                c.chosen = p
                chosen_girls.append(c)
                self.emit_event('girl_chosen', c)

        # mix char class with player -->
        for c in chosen_girls:
            p = c.chosen
            mixin_character(p, c.char_cls)
            p.skills = p.skills[:] # make it instance variable
            ehclasses.extend(p.eventhandlers_required)

        # this will make UIEventHook the last one
        # BUT WHY? FORGOT BUT THIS CAUSES PROBLEMS, REVERT
        # PROBLEM:
        # Reject prompt string should appear when the action fired,
        # actually appears after the whole reject process finished,
        # IN REVERSE ORDER.
        #self.event_handlers[:] = EventHandler.make_list(ehclasses) + self.event_handlers
        self.event_handlers.extend(EventHandler.make_list(ehclasses))

        for i, p in enumerate(self.players):
            p.cards = CardList(p, CardList.HANDCARD) # Cards in hand
            p.showncards = CardList(p, CardList.SHOWNCARD) # Cards which are shown to the others, treated as 'Cards in hand'
            p.equips = CardList(p, CardList.EQUIPS) # Equipments
            p.fatetell = CardList(p, CardList.FATETELL) # Cards in the Fatetell Zone
            p.special = CardList(p, CardList.SPECIAL) # used on special purpose

            p.tags = defaultdict(int)

            p.life = p.maxlife
            p.dead = False
            p.need_shuffle = False
            p.identity = Identity()
            p.identity.type = (Identity.TYPE.HAKUREI, Identity.TYPE.MORIYA)[i%2]

        for p in self.players:
            self.process_action(RevealIdentity(p))

        self.emit_event('game_begin', self)

        # roll
        roll = range(len(self.players))
        random.shuffle(roll)
        pl = self.players
        roll = sync_primitive(roll, pl)

        roll = [pl[i] for i in roll]

        self.emit_event('game_roll', roll)

        first = roll[0]

        for p in roll:
            if p.user_input('choose_option', ActFirst):
                first = p
                break
        # ----

        try:
            for p in self.players:
                self.process_action(DrawCards(p, amount=4 if p.force == first.force else 5))

            pl = self.players.rotate_to(first)

            for i, p in enumerate(cycle(pl)):
                if i >= 6000: break
                if not p.dead:
                    self.emit_event('player_turn', p)
                    self.process_action(PlayerTurn(p))
        except GameEnded:
            pass

    def game_ended(self):
        forces = self.forces
        return any(
            all(p.dead or p.dropped for p in f)
            for f in forces
        )

class THBattle1v1DBG(THBattle):
    n_persons = 2