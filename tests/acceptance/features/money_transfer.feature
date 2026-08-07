@bdd
Feature: Money transfer
  As an account holder
  I want to move money from one of my accounts to another
  So the funds end up where I need them

  The scenarios are written the way the user tells it -- "take funds from the
  source, put them in the destination" -- which is the claim DCI makes about
  the code as well: the context should read like this file.

  Background:
    Given an account "Alice" with 1000 ARS
    And an account "Bob" with 0 ARS

  Scenario: The money moves from source to destination
    When "Alice" transfers 250 ARS to "Bob"
    Then "Alice" has 750 ARS
    And "Bob" has 250 ARS

  Scenario: A transfer beyond the balance is refused
    When "Alice" tries to transfer 5000 ARS to "Bob"
    Then it fails for insufficient funds
    And "Alice" has 1000 ARS
    And "Bob" has 0 ARS

  Scenario: The kinds of money have to agree
    When "Alice" tries to transfer 250 USD to "Bob"
    Then it fails because the kinds of money differ

  Scenario: The same account plays the opposite role next time
    When "Alice" transfers 250 ARS to "Bob"
    And "Bob" transfers 100 ARS to "Alice"
    Then "Alice" has 850 ARS
    And "Bob" has 150 ARS

  Scenario: A participant only plays its role while the transfer lasts
    When "Alice" transfers 250 ARS to "Bob"
    Then "Alice" cannot transfer on her own
