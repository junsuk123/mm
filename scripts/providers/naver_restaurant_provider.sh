#!/bin/sh

naver_get_restaurants_by_food() {
  food_name=$1
  location=$2

  python3 "$PROJECT_ROOT/src/naver_restaurant_api.py" --query "$food_name" --location "$location"
}
