""""
Main module that serves as an entry point for Vakt decisions.
Also contains Inquiry class.
"""

import logging

from .util import JsonSerializer, PrettyPrint
from .audit import policies_message_class as audit_policies_msg_class
from .effects import ALLOW_ACCESS, DENY_ACCESS


log = logging.getLogger(__name__)
audit_log = logging.getLogger('vakt.audit')


class Inquiry(JsonSerializer, PrettyPrint):
    """Holds all the information about the inquired intent.
    Is responsible to decisions if the inquired intent allowed or not."""

    def __init__(self, resource=None, action=None, subject=None, context=None):
        # explicitly assign empty strings instead of occasional None, (), etc.
        self.resource = resource or ''
        self.action = action or ''
        self.subject = subject or ''
        self.context = context or {}

    @classmethod
    def from_json(cls, data):
        props = cls._parse(data)
        return cls(**props)

    def to_json_sorted(self):
        """
        Get JSON representation with all keys sorted.
        """
        return super().to_json(sort=True)

    def __eq__(self, other):
        """
        If inquiries have the same contents - they are equal
        """
        return self.to_json_sorted() == other.to_json_sorted()

    def __hash__(self):
        """
        We do not use to_json as contents representation, because strings are not guaranteed
        to be hashed consistently across different python processes.
        """
        return hash(tuple((ord(c) for c in self.to_json_sorted())))


class Guard:
    """
    Executor of policy checks.
    Given a storage and a checker it can decide via `is_allowed` method if a given inquiry allowed or not.
    """

    def __init__(self, storage, checker):
        self.storage = storage
        self.checker = checker

    def is_allowed(self, inquiry):
        """
        Is given inquiry intent allowed or not?
        Same as `is_allowed_check`, but also logs policy enforcement decisions to log for every incoming inquiry.
        Is meant to be used by an end-user.
        """
        answer = self.is_allowed_check(inquiry)
        if answer:
            log.info('Incoming Inquiry was allowed', inquiry)
        else:
            log.info('Incoming Inquiry was rejected', inquiry)
        return answer

    def is_allowed_check(self, inquiry):
        """
        Is given inquiry intent allowed or not?
        Does not log answers.
        Is not meant to be called by an end-user. Use it only if you want the core functionality of allowance check.
        """
        try:
            policies = self.storage.find_for_inquiry(inquiry, self.checker)
            # Storage is not obliged to do the exact policies match. It's up to the storage
            # to decide what policies to return. So we need a more correct programmatically done check.
            answer = self.check_policies_allow(inquiry, policies)
        except Exception:
            log.exception('Unexpected exception occurred while checking Inquiry %s', inquiry)
            answer = False
        return answer

    def check_policies_allow(self, inquiry, policies):
        """
        Check if any of a given policy allows a specified inquiry
        """
        apc = audit_policies_msg_class()
        # If no policies found or None is given -> deny access!
        if not policies:
            audit_log.info('Denied: no potential policies for inquiry were found', extra={
                'effect': DENY_ACCESS, 'inquiry': inquiry,
                'policies': apc([]), 'deciders': apc([]),
            })
            return False

        # Filter policies that fit Inquiry by its attributes.
        filtered = [p for p in policies if
                    self.checker.fits(p, 'actions', inquiry.action, inquiry) and
                    self.checker.fits(p, 'subjects', inquiry.subject, inquiry) and
                    self.checker.fits(p, 'resources', inquiry.resource, inquiry) and
                    self.check_context_restriction(p, inquiry)]

        # no policies -> deny access!
        # if we have 2 or more similar policies - all of them should have allow effect, otherwise -> deny access!

        # return len(filtered) > 0 and all(p.allow_access() for p in filtered)
        result = False
        for p in filtered:
            if not p.allow_access():
                # todo - pass filtered?
                audit_log.info('Denied: one of matching policies has deny effect', extra={
                    'effect': DENY_ACCESS, 'inquiry': inquiry,
                    'policies': apc(policies), 'deciders': apc([p]),
                })
                return False
            else:
                result = True

        audit_log.info('Allowed: all matching policies have allow effect', extra={
            'effect': ALLOW_ACCESS, 'inquiry': inquiry,
            'policies': apc(policies), 'deciders': apc(filtered),
        })
        return result

    @staticmethod
    def check_context_restriction(policy, inquiry):
        """
        Check if context restriction in the policy is satisfied for a given inquiry's context.
        If at least one rule is not present in Inquiry's context -> deny access.
        If at least one rule provided in Inquiry's context is not satisfied -> deny access.
        """
        for key, rule in policy.context.items():
            try:
                ctx_value = inquiry.context[key]
            except KeyError:
                log.debug("No key '%s' found in Inquiry context", key)
                return False
            if not rule.satisfied(ctx_value, inquiry):
                return False
        return True
