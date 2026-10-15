# Category group GraphQL source evidence

Retrieved 2026-10-15. These are public client source definitions, not an official Monarch API contract and not live account mutation results. No authentication data was read and no account mutation was run for this research.

Primary implementation: thedavidweng/monarchmoney-cli commit 21dc0677a3e1ce718db81af70403eee6bd2ced7c.

## create_group.graphql

Source: https://github.com/thedavidweng/monarchmoney-cli/blob/21dc0677a3e1ce718db81af70403eee6bd2ced7c/queries/categories/create_group.graphql

```graphql
mutation Common_CreateCategoryGroup($input: CreateCategoryGroupInput!) {
  createCategoryGroup(input: $input) {
    categoryGroup {
      id
      name
      order
      type
    }
  }
}
```

## update_group.graphql

Source: https://github.com/thedavidweng/monarchmoney-cli/blob/21dc0677a3e1ce718db81af70403eee6bd2ced7c/queries/categories/update_group.graphql

```graphql
mutation Common_UpdateCategoryGroup($input: UpdateCategoryGroupInput!) {
  updateCategoryGroup(input: $input) {
    categoryGroup {
      id
      name
      order
      type
      color
      groupLevelBudgetingEnabled
      budgetVariability
      rolloverPeriod {
        id
        startMonth
        endMonth
        startingBalance
      }
    }
  }
}
```

## Verified input construction

Source: https://github.com/thedavidweng/monarchmoney-cli/blob/21dc0677a3e1ce718db81af70403eee6bd2ced7c/internal/monarch/categories.go

The implementation of CreateCategoryGroup sends input with name and type. UpdateCategoryGroup starts input with id and conditionally adds only provided options, including name and groupLevelBudgetingEnabled. Those are enough for the current create/rename/budget-mode scope. The public code also offers budgetVariability and rollover fields, but this MCP implementation should omit them because existing account API evidence indicates some group fields are unsupported and because changing rollover is outside the current scope.

## Payload and error evidence

The create operation returns createCategoryGroup.categoryGroup. The public client explicitly treats a null/missing categoryGroup as a schema error. The update operation returns updateCategoryGroup.categoryGroup. Neither mutation selection in the public source requests a payload errors field, and the public create mutation type documentation lists only categoryGroup. Do not assume an errors selection is available merely because the category update mutation has one. GraphQL transport errors, a missing returned entity, mismatched entity ID/fields, and readback mismatches must not be reported as success.

## Public schema corroboration

https://monarch-graphql.ajzbc.com/types/inputs/create-category-group-input/ showed CreateCategoryGroupInput.name as String!, type as String!, and groupLevelBudgetingEnabled as Boolean. Other fields are optional. https://monarch-graphql.ajzbc.com/types/objects/create-category-group-mutation/ lists categoryGroup: CategoryGroup as its sole payload field.

The public schema documentation is auto-generated/unofficial; the current whole-schema download returned HTTP403, and the update input/type pages could not be fetched by the web tool. No workaround was attempted. Public client source remains the evidence for exact update input and operation names.

## Narrow safe selection for current implementation

Use categoryGroups { id name order type groupLevelBudgetingEnabled categories { id name } } for group readback, based on fields already observed successfully in this account and public source. Use id name order type groupLevelBudgetingEnabled in mutation entity selection; omit public source's color/budgetVariability/rollover fields unless separately verified. This narrowing changes only returned fields, not mutation arguments.
